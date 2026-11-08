import pytest
from fastapi import HTTPException
from app.security import validate_url

def test_blocks_localhost():
    with pytest.raises(HTTPException): validate_url("http://localhost:8000")
def test_blocks_file_scheme():
    with pytest.raises(HTTPException): validate_url("file:///etc/passwd")
def test_blocks_url_credentials():
    with pytest.raises(HTTPException): validate_url("https://user:pass@example.com")
