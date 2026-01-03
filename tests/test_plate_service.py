# tests/test_plate_service.py
"""
Unit tests for plate service - validates plate normalization, hashing, 
visitor tracking, and trusted plate checking without needing real images.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path

from packages.perception.plate_service import (
    PlateService,
    normalize_plate_text,
    plate_hmac_hex,
)
from packages.perception.plate_heurystics import (
    is_plate_candidate,
    is_plate_component,
    PlateModifiers,
)


@pytest.fixture
def plate_service():
    """Create a plate service with a test secret key."""
    secret_key = b"test_secret_key_16bytes_minimum!"
    return PlateService(secret_key=secret_key)


@pytest.fixture
def test_db(plate_service):
    """Create a temporary test database with plate service schema."""
    db_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path.close()
    
    conn = sqlite3.connect(db_path.name)
    plate_service.ensure_schema(conn)
    
    yield conn
    
    conn.close()
    Path(db_path.name).unlink()


class TestPlateNormalization:
    """Test plate text normalization and hashing."""
    
    def test_normalize_simple_plate(self):
        """Test basic plate normalization removes spaces and lowercase."""
        assert normalize_plate_text("abc 123") == "ABC123"
        assert normalize_plate_text("ABC-123") == "ABC123"
        assert normalize_plate_text("abc123") == "ABC123"
    
    def test_normalize_removes_special_chars(self):
        """Test normalization removes special characters."""
        assert normalize_plate_text("AB#C@123!") == "ABC123"
        assert normalize_plate_text("1-2-3-A-B-C") == "123ABC"
    
    def test_normalize_empty_string(self):
        """Test normalization of empty/invalid input."""
        assert normalize_plate_text("") == ""
        assert normalize_plate_text("###") == ""
        assert normalize_plate_text("   ") == ""
    
    def test_hmac_consistency(self):
        """Test that same plate always produces same hash."""
        secret = b"test_secret_key_16bytes!"
        plate1 = "ABC123"
        plate2 = "ABC123"
        
        hash1 = plate_hmac_hex(secret, plate1)
        hash2 = plate_hmac_hex(secret, plate2)
        
        assert hash1 == hash2
        assert len(hash1) == 32  # 16 bytes * 2 hex chars
    
    def test_hmac_different_plates(self):
        """Test that different plates produce different hashes."""
        secret = b"test_secret_key_16bytes!"
        
        hash1 = plate_hmac_hex(secret, "ABC123")
        hash2 = plate_hmac_hex(secret, "XYZ789")
        
        assert hash1 != hash2
    
    def test_hmac_different_secrets(self):
        """Test that same plate with different secrets produces different hashes."""
        plate = "ABC123"
        
        hash1 = plate_hmac_hex(b"secret1_16bytes!!", plate)
        hash2 = plate_hmac_hex(b"secret2_16bytes!!", plate)
        
        assert hash1 != hash2


class TestPlateVisitorTracking:
    """Test plate visitor recording and repeat detection."""
    
    def test_first_plate_visit(self, plate_service, test_db):
        """Test first time a plate is seen."""
        result = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC 123",
            camera_id=1,
            seen_ts=1000000,
        )
        
        assert result is not None
        assert result.is_repeat is False
        assert result.visit_count == 1
        assert result.first_seen_ts == 1000000
        assert result.last_seen_ts == 1000000
    
    def test_repeat_plate_visit(self, plate_service, test_db):
        """Test subsequent visits by same plate."""
        # First visit
        result1 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC123",
            camera_id=1,
            seen_ts=1000000,
        )
        
        # Second visit
        result2 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC123",
            camera_id=1,
            seen_ts=2000000,
        )
        
        assert result1.is_repeat is False
        assert result2.is_repeat is True
        assert result2.visit_count == 2
        assert result2.first_seen_ts == 1000000  # Original timestamp
        assert result2.last_seen_ts == 2000000   # Updated timestamp
    
    def test_normalized_plates_match(self, plate_service, test_db):
        """Test that differently formatted plates are recognized as same."""
        # First visit with one format
        result1 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC-123",
            camera_id=1,
            seen_ts=1000000,
        )
        
        # Second visit with different format
        result2 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="abc 123",
            camera_id=1,
            seen_ts=2000000,
        )
        
        assert result1.is_repeat is False
        assert result2.is_repeat is True
        assert result2.visit_count == 2
    
    def test_invalid_plate_text(self, plate_service, test_db):
        """Test that invalid plate text returns None."""
        result = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="###",  # No valid alphanumeric
            camera_id=1,
            seen_ts=1000000,
        )
        
        assert result is None


class TestTrustedPlates:
    """Test trusted plate management."""
    
    def test_add_trusted_plate(self, plate_service, test_db):
        """Test adding a trusted plate."""
        plate_hmac = plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC123",
            label="Family Car",
            now_ts=1000000,
        )
        
        assert plate_hmac is not None
        assert len(plate_hmac) == 32  # 16 bytes hex
    
    def test_check_trusted_plate(self, plate_service, test_db):
        """Test checking if a plate is trusted."""
        # Add trusted plate
        plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC123",
            label="Family Car",
        )
        
        # Check it
        result = plate_service.is_plate_trusted(test_db, "ABC123")
        
        assert result is not None
        assert result["label"] == "Family Car"
        assert result["enabled"] is True
    
    def test_trusted_plate_normalization(self, plate_service, test_db):
        """Test that trusted plates recognize different formats."""
        # Add with one format
        plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC-123",
            label="Family Car",
        )
        
        # Check with different format
        result = plate_service.is_plate_trusted(test_db, "abc 123")
        
        assert result is not None
        assert result["label"] == "Family Car"
    
    def test_untrusted_plate(self, plate_service, test_db):
        """Test that unknown plates return None."""
        result = plate_service.is_plate_trusted(test_db, "XYZ789")
        assert result is None
    
    def test_disabled_trusted_plate(self, plate_service, test_db):
        """Test that disabled plates are not returned as trusted."""
        # Add disabled plate
        plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC123",
            label="Family Car",
            enabled=False,
        )
        
        # Should not be found
        result = plate_service.is_plate_trusted(test_db, "ABC123")
        assert result is None
    
    def test_update_trusted_plate(self, plate_service, test_db):
        """Test updating an existing trusted plate."""
        # Add initial
        plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC123",
            label="Old Label",
        )
        
        # Update
        plate_service.add_trusted_plate(
            test_db,
            raw_plate_text="ABC123",
            label="New Label",
        )
        
        # Check updated
        result = plate_service.is_plate_trusted(test_db, "ABC123")
        assert result["label"] == "New Label"


class TestPlateServiceEdgeCases:
    """Test edge cases and error handling."""
    
    def test_invalid_secret_key(self):
        """Test that short secret keys are rejected."""
        with pytest.raises(ValueError, match="secret_key must be >= 16 bytes"):
            PlateService(secret_key=b"short")
    
    def test_empty_secret_key(self):
        """Test that empty secret key is rejected."""
        with pytest.raises(ValueError, match="secret_key must be >= 16 bytes"):
            PlateService(secret_key=b"")
    
    def test_multiple_visits_different_cameras(self, plate_service, test_db):
        """Test that visits from different cameras are tracked."""
        # Visit from camera 1
        result1 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC123",
            camera_id=1,
            seen_ts=1000000,
        )
        
        # Visit from camera 2
        result2 = plate_service.upsert_plate_visit(
            test_db,
            raw_plate_text="ABC123",
            camera_id=2,
            seen_ts=2000000,
        )
        
        assert result2.is_repeat is True
        assert result2.visit_count == 2
        
        # Check last_camera_id is updated in database
        row = test_db.execute(
            "SELECT last_camera_id FROM plate_visitors WHERE plate_hmac = ?",
            (result2.plate_hmac,)
        ).fetchone()
        
        assert row[0] == 2  # Should be the most recent camera


class TestPlateValidation:
    """Test plate candidate validation heuristics."""
    
    def test_valid_plate_candidates(self):
        """Test that valid plate formats are recognized."""
        # Standard US plates (mix of letters and numbers, 5-8 chars)
        assert is_plate_candidate("ABC123") is True
        assert is_plate_candidate("1ABC234") is True
        assert is_plate_candidate("AB12CD") is True
        assert is_plate_candidate("ABC1234") is True
        assert is_plate_candidate("12ABC34") is True
    
    def test_invalid_plate_candidates(self):
        """Test that invalid formats are rejected."""
        # Too short
        assert is_plate_candidate("AB12") is False
        assert is_plate_candidate("A1") is False
        
        # Too long
        assert is_plate_candidate("ABC123456") is False
        
        # No digits (all letters)
        assert is_plate_candidate("ABCDEF") is False
        assert is_plate_candidate("ABCDEFG") is False
        
        # No letters (all digits)
        assert is_plate_candidate("123456") is False
        assert is_plate_candidate("1234567") is False
        
        # Contains special characters
        assert is_plate_candidate("ABC-123") is False
        assert is_plate_candidate("ABC 123") is False
        assert is_plate_candidate("ABC.123") is False
    
    def test_edge_case_lengths(self):
        """Test boundary conditions for plate length."""
        # Exactly min length (5)
        assert is_plate_candidate("AB123") is True
        assert is_plate_candidate("A1234") is True
        
        # Exactly max length (8)
        assert is_plate_candidate("ABC12345") is True
        assert is_plate_candidate("AB123456") is True
        
        # Just under min (4)
        assert is_plate_candidate("AB12") is False
        
        # Just over max (9)
        assert is_plate_candidate("ABC123456") is False
    
    def test_plate_components(self):
        """Test recognition of plate fragments (for grouping)."""
        # Valid components (2-4 chars, alphanumeric)
        assert is_plate_component("AB") is True
        assert is_plate_component("123") is True
        assert is_plate_component("ABC") is True
        assert is_plate_component("1234") is True
        assert is_plate_component("AB12") is True
        
        # Invalid components
        assert is_plate_component("A") is False  # Too short
        assert is_plate_component("ABCDE") is False  # Too long
        assert is_plate_component("AB-C") is False  # Special char
        assert is_plate_component("") is False  # Empty
    
    def test_common_ocr_errors_rejected(self):
        """Test that common OCR misreads are rejected."""
        # Words that might appear near vehicles
        assert is_plate_candidate("DELIVERY") is False  # All letters, too long
        assert is_plate_candidate("AMAZON") is False  # All letters
        assert is_plate_candidate("FEDEX") is False  # All letters
        assert is_plate_candidate("SERVICE") is False  # All letters, too long
        
        # Numbers only
        assert is_plate_candidate("123456") is False
        assert is_plate_candidate("128594") is False
    
    def test_international_style_plates(self):
        """Test various international plate styles that should be recognized."""
        # European style (mix of letters/numbers)
        assert is_plate_candidate("AB12CD") is True
        assert is_plate_candidate("ABC123D") is True
        
        # Some Asian markets (alphanumeric)
        assert is_plate_candidate("1ABC234") is True
        
        # Vanity plates
        assert is_plate_candidate("GO2BED") is True
        assert is_plate_candidate("LUV2SKI") is True
    
    def test_custom_modifiers(self):
        """Test plate validation with custom length constraints."""
        mods = PlateModifiers(
            min_candidate_len=6,
            max_candidate_len=7,
        )
        
        # Should accept 6-7 char plates
        assert is_plate_candidate("ABC123", mods) is True
        assert is_plate_candidate("ABC1234", mods) is True
        
        # Should reject 5 char (now too short)
        assert is_plate_candidate("AB123", mods) is False
        
        # Should reject 8 char (now too long)
        assert is_plate_candidate("ABC12345", mods) is False
    
    def test_whitespace_handling(self):
        """Test that whitespace is handled properly."""
        # Leading/trailing whitespace should be stripped
        assert is_plate_candidate("  ABC123  ") is True
        assert is_plate_candidate("\tABC123\n") is True
        
        # Internal whitespace makes it invalid
        assert is_plate_candidate("ABC 123") is False
