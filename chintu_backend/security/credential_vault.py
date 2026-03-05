"""Secure credential vault for storing login information.

Uses AES-256 encryption with PBKDF2 key derivation.
Credentials are stored encrypted on disk with master password protection.
"""

import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import cryptography, fallback to basic encryption if not available
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    # No fallback - we will fail securely if methods are called


@dataclass
class Credential:
    """Represents a stored credential."""
    site: str
    username: str
    password: str  # Encrypted in storage
    url: str
    created_at: str
    last_used: Optional[str] = None
    notes: Optional[str] = None


class CredentialVault:
    """Secure credential storage with master password encryption."""
    
    def __init__(self, vault_path: Optional[Path] = None):
        """Initialize the credential vault.
        
        Args:
            vault_path: Path to store encrypted credentials
        """
        if vault_path is None:
            vault_path = Path.home() / ".chintu" / "vault"
        self.vault_path = Path(vault_path)
        self.vault_path.mkdir(parents=True, exist_ok=True)
        
        self._credentials_file = self.vault_path / "credentials.enc"
        self._salt_file = self.vault_path / "salt"
        self._hash_file = self.vault_path / "master.hash"
        
        self._key: Optional[bytes] = None
        self._fernet: Optional[Fernet] = None
        self._unlocked = False
        self._credentials: Dict[str, Credential] = {}
        
        logger.info(f"CredentialVault initialized at {self.vault_path}")
        
    @property
    def is_setup(self) -> bool:
        """Check if vault has been set up with a master password."""
        return self._hash_file.exists()
    
    @property
    def is_unlocked(self) -> bool:
        """Check if vault is currently unlocked."""
        return self._unlocked
    
    def setup(self, master_password: str) -> bool:
        """Set up the vault with a new master password.
        
        Args:
            master_password: The master password to use
            
        Returns:
            True if setup successful
        """
        if self.is_setup:
            logger.warning("Vault is already set up. Use change_master_password instead.")
            return False
            
        if len(master_password) < 8:
            logger.error("Master password must be at least 8 characters")
            return False
        
        # Generate random salt
        salt = os.urandom(32)
        self._salt_file.write_bytes(salt)
        
        # Hash the master password for verification
        password_hash = self._hash_password(master_password, salt)
        self._hash_file.write_bytes(password_hash)
        
        # Derive encryption key
        self._derive_key(master_password, salt)
        self._unlocked = True
        self._credentials = {}
        
        # Save empty credentials file
        self._save_credentials()
        
        logger.info("Vault setup complete")
        return True
    
    def unlock(self, master_password: str) -> bool:
        """Unlock the vault with the master password.
        
        Args:
            master_password: The master password
            
        Returns:
            True if unlock successful
        """
        if not self.is_setup:
            logger.error("Vault is not set up. Call setup() first.")
            return False
            
        salt = self._salt_file.read_bytes()
        stored_hash = self._hash_file.read_bytes()
        
        # Verify password
        password_hash = self._hash_password(master_password, salt)
        if password_hash != stored_hash:
            logger.warning("Invalid master password")
            return False
        
        # Derive encryption key
        self._derive_key(master_password, salt)
        self._unlocked = True
        
        # Load credentials
        self._load_credentials()
        
        logger.info("Vault unlocked successfully")
        return True
    
    def lock(self):
        """Lock the vault and clear sensitive data from memory."""
        self._key = None
        self._fernet = None
        self._unlocked = False
        self._credentials = {}
        logger.info("Vault locked")
    
    def add_credential(self, site: str, username: str, password: str,
                       url: str, notes: Optional[str] = None) -> bool:
        """Add a new credential to the vault.
        
        Args:
            site: Site name (e.g., "gmail", "linkedin")
            username: Username/email
            password: Password (will be encrypted)
            url: Login URL
            notes: Optional notes
            
        Returns:
            True if added successfully
        """
        if not self._unlocked:
            logger.error("Vault is locked. Call unlock() first.")
            return False
        
        site_key = site.lower().strip()
        
        credential = Credential(
            site=site,
            username=username,
            password=password,
            url=url,
            created_at=datetime.now().isoformat(),
            notes=notes
        )
        
        self._credentials[site_key] = credential
        self._save_credentials()
        
        logger.info(f"Added credential for {site}")
        return True
    
    def get_credential(self, site: str) -> Optional[Credential]:
        """Get a credential by site name.
        
        Args:
            site: Site name to look up
            
        Returns:
            Credential if found, None otherwise
        """
        if not self._unlocked:
            logger.error("Vault is locked. Call unlock() first.")
            return None
            
        site_key = site.lower().strip()
        cred = self._credentials.get(site_key)
        
        if cred:
            # Update last used
            cred.last_used = datetime.now().isoformat()
            self._save_credentials()
            
        return cred
    
    def remove_credential(self, site: str) -> bool:
        """Remove a credential from the vault.
        
        Args:
            site: Site name to remove
            
        Returns:
            True if removed, False if not found
        """
        if not self._unlocked:
            logger.error("Vault is locked. Call unlock() first.")
            return False
            
        site_key = site.lower().strip()
        if site_key in self._credentials:
            del self._credentials[site_key]
            self._save_credentials()
            logger.info(f"Removed credential for {site}")
            return True
        return False
    
    def list_sites(self) -> List[str]:
        """List all stored site names.
        
        Returns:
            List of site names
        """
        if not self._unlocked:
            return []
        return list(self._credentials.keys())
    
    def _hash_password(self, password: str, salt: bytes) -> bytes:
        """Hash password with salt using SHA-256."""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt,
            100000  # iterations
        )
    
    def _derive_key(self, password: str, salt: bytes):
        """Derive encryption key from password."""
        if CRYPTO_AVAILABLE:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            self._key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self._fernet = Fernet(self._key)
            self._key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self._fernet = Fernet(self._key)
        else:
             raise ImportError("Strict Security Enforcement: 'cryptography' library is missing. Cannot derive secure keys.")
    
    def _encrypt(self, data: str) -> str:
        """Encrypt data."""
        if CRYPTO_AVAILABLE and self._fernet:
            return self._fernet.encrypt(data.encode()).decode()
        else:
             raise ImportError("Strict Security Enforcement: 'cryptography' library matching. Cannot encrypt.")
    
    def _decrypt(self, data: str) -> str:
        """Decrypt data."""
        if CRYPTO_AVAILABLE and self._fernet:
            return self._fernet.decrypt(data.encode()).decode()
        else:
             raise ImportError("Strict Security Enforcement: 'cryptography' library matching. Cannot decrypt.")
    
    def _save_credentials(self):
        """Save credentials to encrypted file."""
        if not self._unlocked:
            return
        
        # Serialize credentials
        data = {}
        for site, cred in self._credentials.items():
            cred_dict = asdict(cred)
            data[site] = cred_dict
        
        json_data = json.dumps(data)
        encrypted = self._encrypt(json_data)
        
        self._credentials_file.write_text(encrypted)
        logger.debug("Credentials saved")
    
    def _load_credentials(self):
        """Load credentials from encrypted file."""
        if not self._credentials_file.exists():
            self._credentials = {}
            return
        
        try:
            encrypted = self._credentials_file.read_text()
            json_data = self._decrypt(encrypted)
            data = json.loads(json_data)
            
            self._credentials = {}
            for site, cred_dict in data.items():
                self._credentials[site] = Credential(**cred_dict)
                
            logger.debug(f"Loaded {len(self._credentials)} credentials")
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            self._credentials = {}


# Global vault instance
_vault: Optional[CredentialVault] = None


def get_credential_vault() -> CredentialVault:
    """Get the global CredentialVault instance."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
