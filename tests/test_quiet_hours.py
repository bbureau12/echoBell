"""Tests for quiet hours service"""
import pytest
import sqlite3
from datetime import datetime, time
from packages.data.quiet_hours_service import QuietHoursService, QuietHour


@pytest.fixture
def db():
    """Create in-memory database with quiet_hours table"""
    conn = sqlite3.connect(':memory:')
    conn.executescript("""
        CREATE TABLE quiet_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),
            start_time TEXT NOT NULL CHECK(length(start_time) = 5 AND start_time LIKE '__:__'),
            end_time TEXT NOT NULL CHECK(length(end_time) = 5 AND end_time LIKE '__:__'),
            enabled INTEGER DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_quiet_hours_weekday ON quiet_hours(weekday);
        CREATE INDEX idx_quiet_hours_enabled ON quiet_hours(enabled);
    """)
    yield conn
    conn.close()


class TestQuietHourCRUD:
    """Test basic CRUD operations"""
    
    def test_create_quiet_hour(self, db):
        """Test creating a quiet hour entry"""
        qh_id = QuietHoursService.create_quiet_hour(
            db,
            name="Weeknight Sleep",
            weekday=0,  # Monday
            start_time="22:00",
            end_time="07:00",
            enabled=True
        )
        
        assert qh_id > 0
        
        # Verify it was created
        quiet_hours = QuietHoursService.get_quiet_hours(db, enabled_only=False)
        assert len(quiet_hours) == 1
        assert quiet_hours[0].name == "Weeknight Sleep"
        assert quiet_hours[0].weekday == 0
        assert quiet_hours[0].start_time == "22:00"
        assert quiet_hours[0].end_time == "07:00"
        assert quiet_hours[0].enabled is True
    
    def test_get_quiet_hours_for_day(self, db):
        """Test getting quiet hours for a specific weekday"""
        # Create quiet hours for Monday and Tuesday
        QuietHoursService.create_quiet_hour(db, "Monday Sleep", 0, "22:00", "07:00")
        QuietHoursService.create_quiet_hour(db, "Tuesday Sleep", 1, "22:00", "07:00")
        QuietHoursService.create_quiet_hour(db, "Monday Lunch", 0, "12:00", "13:00")
        
        # Get Monday quiet hours
        monday_qh = QuietHoursService.get_quiet_hours_for_day(db, weekday=0)
        assert len(monday_qh) == 2
        assert all(qh.weekday == 0 for qh in monday_qh)
        
        # Should be sorted by start_time
        assert monday_qh[0].start_time == "12:00"
        assert monday_qh[1].start_time == "22:00"
    
    def test_update_quiet_hour(self, db):
        """Test updating quiet hour fields"""
        qh_id = QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        QuietHoursService.update_quiet_hour(
            db,
            qh_id,
            name="Updated Sleep",
            start_time="23:00",
            enabled=False
        )
        
        quiet_hours = QuietHoursService.get_quiet_hours(db, enabled_only=False)
        assert quiet_hours[0].name == "Updated Sleep"
        assert quiet_hours[0].start_time == "23:00"
        assert quiet_hours[0].enabled is False
    
    def test_delete_quiet_hour(self, db):
        """Test deleting a quiet hour entry"""
        qh_id = QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        QuietHoursService.delete_quiet_hour(db, qh_id)
        
        quiet_hours = QuietHoursService.get_quiet_hours(db, enabled_only=False)
        assert len(quiet_hours) == 0
    
    def test_enabled_only_filter(self, db):
        """Test filtering by enabled status"""
        QuietHoursService.create_quiet_hour(db, "Enabled", 0, "22:00", "07:00", enabled=True)
        QuietHoursService.create_quiet_hour(db, "Disabled", 1, "22:00", "07:00", enabled=False)
        
        enabled_only = QuietHoursService.get_quiet_hours(db, enabled_only=True)
        all_qh = QuietHoursService.get_quiet_hours(db, enabled_only=False)
        
        assert len(enabled_only) == 1
        assert len(all_qh) == 2
        assert enabled_only[0].name == "Enabled"


class TestQuietHourDetection:
    """Test quiet time detection logic"""
    
    def test_is_quiet_time_normal_period(self, db):
        """Test quiet time detection for normal (non-overnight) periods"""
        # Lunch quiet hour: 12:00-13:00 on Monday
        QuietHoursService.create_quiet_hour(db, "Lunch", 0, "12:00", "13:00")
        
        # Monday at 12:30 (inside quiet hour)
        dt = datetime(2026, 2, 2, 12, 30)  # Monday
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Monday at 11:30 (before quiet hour)
        dt = datetime(2026, 2, 2, 11, 30)
        assert QuietHoursService.is_quiet_time(db, dt) is False
        
        # Monday at 13:30 (after quiet hour)
        dt = datetime(2026, 2, 2, 13, 30)
        assert QuietHoursService.is_quiet_time(db, dt) is False
    
    def test_is_quiet_time_overnight_period(self, db):
        """Test quiet time detection for overnight periods"""
        # Sleep: 22:00-07:00 on Monday
        QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        # Monday at 23:00 (inside quiet hour, before midnight)
        dt = datetime(2026, 2, 2, 23, 0)  # Monday
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Tuesday at 06:00 (inside quiet hour, after midnight)
        dt = datetime(2026, 2, 3, 6, 0)  # Tuesday
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Tuesday at 08:00 (after quiet hour ended)
        dt = datetime(2026, 2, 3, 8, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is False
        
        # Monday at 20:00 (before quiet hour starts)
        dt = datetime(2026, 2, 2, 20, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is False
    
    def test_is_quiet_time_disabled_entry(self, db):
        """Test that disabled quiet hours are not detected"""
        QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00", enabled=False)
        
        dt = datetime(2026, 2, 2, 23, 0)  # Monday at 23:00
        assert QuietHoursService.is_quiet_time(db, dt) is False
    
    def test_is_quiet_time_multiple_periods(self, db):
        """Test with multiple quiet hour periods"""
        # Lunch and sleep on Monday
        QuietHoursService.create_quiet_hour(db, "Lunch", 0, "12:00", "13:00")
        QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        # Test lunch time
        dt = datetime(2026, 2, 2, 12, 30)
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Test between periods
        dt = datetime(2026, 2, 2, 15, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is False
        
        # Test sleep time
        dt = datetime(2026, 2, 2, 23, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is True
    
    def test_get_active_quiet_hours(self, db):
        """Test getting currently active quiet hour entries"""
        QuietHoursService.create_quiet_hour(db, "Lunch", 0, "12:00", "13:00")
        QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        # During lunch
        dt = datetime(2026, 2, 2, 12, 30)  # Monday
        active = QuietHoursService.get_active_quiet_hours(db, dt)
        assert len(active) == 1
        assert active[0].name == "Lunch"
        
        # During sleep (before midnight)
        dt = datetime(2026, 2, 2, 23, 0)
        active = QuietHoursService.get_active_quiet_hours(db, dt)
        assert len(active) == 1
        assert active[0].name == "Sleep"
        
        # During sleep (after midnight)
        dt = datetime(2026, 2, 3, 6, 0)  # Tuesday
        active = QuietHoursService.get_active_quiet_hours(db, dt)
        assert len(active) == 1
        assert active[0].name == "Sleep"
        
        # Not in quiet hours
        dt = datetime(2026, 2, 2, 15, 0)
        active = QuietHoursService.get_active_quiet_hours(db, dt)
        assert len(active) == 0


class TestQuietHourDataclass:
    """Test QuietHour dataclass properties"""
    
    def test_time_conversion_properties(self):
        """Test time string to time object conversion"""
        qh = QuietHour(
            id=1,
            name="Test",
            weekday=0,
            start_time="09:30",
            end_time="17:45",
            enabled=True
        )
        
        assert qh.start_time_obj == time(9, 30)
        assert qh.end_time_obj == time(17, 45)
    
    def test_is_overnight_detection(self):
        """Test overnight period detection"""
        # Normal period
        qh_normal = QuietHour(1, "Normal", 0, "09:00", "17:00", True)
        assert qh_normal.is_overnight() is False
        
        # Overnight period
        qh_overnight = QuietHour(1, "Overnight", 0, "22:00", "07:00", True)
        assert qh_overnight.is_overnight() is True
        
        # Edge case: same time (should not be overnight)
        qh_same = QuietHour(1, "Same", 0, "12:00", "12:00", True)
        assert qh_same.is_overnight() is False


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_boundary_times(self, db):
        """Test quiet hours at exact boundary times"""
        QuietHoursService.create_quiet_hour(db, "Sleep", 0, "22:00", "07:00")
        
        # Exactly at start time (included)
        dt = datetime(2026, 2, 2, 22, 0, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Exactly at end time (excluded)
        dt = datetime(2026, 2, 3, 7, 0, 0)
        assert QuietHoursService.is_quiet_time(db, dt) is False
        
        # One second before end
        dt = datetime(2026, 2, 3, 6, 59, 59)
        assert QuietHoursService.is_quiet_time(db, dt) is True
    
    def test_weekday_wrap_around(self, db):
        """Test overnight period from Sunday to Monday"""
        # Sunday sleep: 22:00-07:00
        QuietHoursService.create_quiet_hour(db, "Sleep", 6, "22:00", "07:00")
        
        # Sunday at 23:00 (inside quiet hour)
        dt = datetime(2026, 2, 8, 23, 0)  # Sunday
        assert QuietHoursService.is_quiet_time(db, dt) is True
        
        # Monday at 06:00 (inside quiet hour, wrapped to Monday)
        dt = datetime(2026, 2, 9, 6, 0)  # Monday
        assert QuietHoursService.is_quiet_time(db, dt) is True
    
    def test_multiple_entries_same_day(self, db):
        """Test multiple quiet hour entries for the same day"""
        QuietHoursService.create_quiet_hour(db, "Morning", 0, "06:00", "08:00")
        QuietHoursService.create_quiet_hour(db, "Lunch", 0, "12:00", "13:00")
        QuietHoursService.create_quiet_hour(db, "Evening", 0, "18:00", "20:00")
        
        # Test each period
        assert QuietHoursService.is_quiet_time(db, datetime(2026, 2, 2, 7, 0)) is True
        assert QuietHoursService.is_quiet_time(db, datetime(2026, 2, 2, 12, 30)) is True
        assert QuietHoursService.is_quiet_time(db, datetime(2026, 2, 2, 19, 0)) is True
        
        # Test between periods
        assert QuietHoursService.is_quiet_time(db, datetime(2026, 2, 2, 10, 0)) is False
        assert QuietHoursService.is_quiet_time(db, datetime(2026, 2, 2, 15, 0)) is False


class TestWeekdayConvention:
    """Test that weekday numbering follows ISO 8601 (0=Monday, 6=Sunday)"""
    
    def test_weekday_mapping(self, db):
        """Verify weekday numbering convention"""
        # Create quiet hours for each day
        days = [
            (0, "Monday"),
            (1, "Tuesday"),
            (2, "Wednesday"),
            (3, "Thursday"),
            (4, "Friday"),
            (5, "Saturday"),
            (6, "Sunday")
        ]
        
        for weekday, name in days:
            QuietHoursService.create_quiet_hour(db, name, weekday, "12:00", "13:00")
        
        # Feb 2, 2026 is a Monday
        # Verify each day matches
        test_dates = [
            (datetime(2026, 2, 2), "Monday"),    # 0
            (datetime(2026, 2, 3), "Tuesday"),   # 1
            (datetime(2026, 2, 4), "Wednesday"), # 2
            (datetime(2026, 2, 5), "Thursday"),  # 3
            (datetime(2026, 2, 6), "Friday"),    # 4
            (datetime(2026, 2, 7), "Saturday"),  # 5
            (datetime(2026, 2, 8), "Sunday"),    # 6
        ]
        
        for dt, expected_name in test_dates:
            # Set time to 12:30 (inside quiet hour)
            dt = dt.replace(hour=12, minute=30)
            active = QuietHoursService.get_active_quiet_hours(db, dt)
            assert len(active) == 1
            assert active[0].name == expected_name


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
