"""
Quiet Hours Service - Time-based notification suppression

Manages quiet hours schedules for reducing or suppressing notifications
during sleep hours, meetings, etc.
"""
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional


@dataclass
class QuietHour:
    """Represents a quiet hours schedule entry"""
    id: int
    name: str
    weekday: int  # 0=Monday, 6=Sunday (ISO 8601)
    start_time: str  # HH:MM (24h format)
    end_time: str  # HH:MM (24h format)
    enabled: bool
    
    @property
    def start_time_obj(self) -> time:
        """Convert start_time string to time object"""
        h, m = map(int, self.start_time.split(':'))
        return time(h, m)
    
    @property
    def end_time_obj(self) -> time:
        """Convert end_time string to time object"""
        h, m = map(int, self.end_time.split(':'))
        return time(h, m)
    
    def is_overnight(self) -> bool:
        """Check if this quiet hour period spans midnight"""
        return self.start_time_obj > self.end_time_obj


class QuietHoursService:
    """Service for managing quiet hours schedules"""
    
    @staticmethod
    def create_quiet_hour(conn, name: str, weekday: int, start_time: str, 
                         end_time: str, enabled: bool = True) -> int:
        """
        Create a new quiet hours entry
        
        Args:
            conn: Database connection
            name: Descriptive name (e.g., "Weeknight Sleep", "Work Hours")
            weekday: Day of week (0=Monday, 6=Sunday)
            start_time: Start time in HH:MM format (24h)
            end_time: End time in HH:MM format (24h)
            enabled: Whether this quiet hour is active
            
        Returns:
            ID of created quiet hour
        """
        cursor = conn.execute(
            """
            INSERT INTO quiet_hours (name, weekday, start_time, end_time, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, weekday, start_time, end_time, 1 if enabled else 0)
        )
        conn.commit()
        return cursor.lastrowid
    
    @staticmethod
    def get_quiet_hours(conn, enabled_only: bool = True) -> list[QuietHour]:
        """
        Get all quiet hours entries
        
        Args:
            conn: Database connection
            enabled_only: If True, only return enabled entries
            
        Returns:
            List of QuietHour objects
        """
        query = "SELECT id, name, weekday, start_time, end_time, enabled FROM quiet_hours"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY weekday, start_time"
        
        cursor = conn.execute(query)
        return [
            QuietHour(
                id=row[0],
                name=row[1],
                weekday=row[2],
                start_time=row[3],
                end_time=row[4],
                enabled=bool(row[5])
            )
            for row in cursor.fetchall()
        ]
    
    @staticmethod
    def get_quiet_hours_for_day(conn, weekday: int, enabled_only: bool = True) -> list[QuietHour]:
        """
        Get quiet hours for a specific weekday
        
        Args:
            conn: Database connection
            weekday: Day of week (0=Monday, 6=Sunday)
            enabled_only: If True, only return enabled entries
            
        Returns:
            List of QuietHour objects for that day
        """
        query = "SELECT id, name, weekday, start_time, end_time, enabled FROM quiet_hours WHERE weekday = ?"
        params = [weekday]
        
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY start_time"
        
        cursor = conn.execute(query, params)
        return [
            QuietHour(
                id=row[0],
                name=row[1],
                weekday=row[2],
                start_time=row[3],
                end_time=row[4],
                enabled=bool(row[5])
            )
            for row in cursor.fetchall()
        ]
    
    @staticmethod
    def update_quiet_hour(conn, quiet_hour_id: int, **kwargs):
        """
        Update a quiet hours entry
        
        Args:
            conn: Database connection
            quiet_hour_id: ID of quiet hour to update
            **kwargs: Fields to update (name, weekday, start_time, end_time, enabled)
        """
        allowed_fields = {'name', 'weekday', 'start_time', 'end_time', 'enabled'}
        fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not fields:
            return
        
        # Convert boolean enabled to int
        if 'enabled' in fields:
            fields['enabled'] = 1 if fields['enabled'] else 0
        
        set_clause = ', '.join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [quiet_hour_id]
        
        conn.execute(
            f"UPDATE quiet_hours SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values
        )
        conn.commit()
    
    @staticmethod
    def delete_quiet_hour(conn, quiet_hour_id: int):
        """Delete a quiet hours entry"""
        conn.execute("DELETE FROM quiet_hours WHERE id = ?", (quiet_hour_id,))
        conn.commit()
    
    @staticmethod
    def is_quiet_time(conn, dt: Optional[datetime] = None) -> bool:
        """
        Check if the given datetime falls within any quiet hours
        
        Args:
            conn: Database connection
            dt: Datetime to check (defaults to now)
            
        Returns:
            True if currently in quiet hours, False otherwise
        """
        if dt is None:
            dt = datetime.now()
        
        # Get weekday (0=Monday, 6=Sunday)
        weekday = dt.weekday()
        current_time = dt.time()
        
        # Get quiet hours for today
        quiet_hours = QuietHoursService.get_quiet_hours_for_day(conn, weekday, enabled_only=True)
        
        for qh in quiet_hours:
            if qh.is_overnight():
                # Period spans midnight (e.g., 22:00 - 07:00)
                if current_time >= qh.start_time_obj or current_time < qh.end_time_obj:
                    return True
            else:
                # Normal period (e.g., 13:00 - 14:00)
                if qh.start_time_obj <= current_time < qh.end_time_obj:
                    return True
        
        # Also check if we're in an overnight period from yesterday
        yesterday = (weekday - 1) % 7
        yesterday_quiet_hours = QuietHoursService.get_quiet_hours_for_day(conn, yesterday, enabled_only=True)
        
        for qh in yesterday_quiet_hours:
            if qh.is_overnight():
                # Check if current time is before the end time
                if current_time < qh.end_time_obj:
                    return True
        
        return False
    
    @staticmethod
    def get_active_quiet_hours(conn, dt: Optional[datetime] = None) -> list[QuietHour]:
        """
        Get all quiet hours that are currently active
        
        Args:
            conn: Database connection
            dt: Datetime to check (defaults to now)
            
        Returns:
            List of currently active QuietHour objects
        """
        if dt is None:
            dt = datetime.now()
        
        weekday = dt.weekday()
        current_time = dt.time()
        active = []
        
        # Check today's quiet hours
        quiet_hours = QuietHoursService.get_quiet_hours_for_day(conn, weekday, enabled_only=True)
        
        for qh in quiet_hours:
            if qh.is_overnight():
                if current_time >= qh.start_time_obj or current_time < qh.end_time_obj:
                    active.append(qh)
            else:
                if qh.start_time_obj <= current_time < qh.end_time_obj:
                    active.append(qh)
        
        # Check yesterday's overnight periods
        yesterday = (weekday - 1) % 7
        yesterday_quiet_hours = QuietHoursService.get_quiet_hours_for_day(conn, yesterday, enabled_only=True)
        
        for qh in yesterday_quiet_hours:
            if qh.is_overnight() and current_time < qh.end_time_obj:
                active.append(qh)
        
        return active
