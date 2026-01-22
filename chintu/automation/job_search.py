"""Job search automation."""

import webbrowser
from urllib.parse import quote_plus
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class JobSearcher:
    """
    Automates job searching on various platforms.
    Opens job search URLs with appropriate parameters.
    """
    
    # Job search platforms with URL templates
    PLATFORMS = {
        "linkedin": {
            "name": "LinkedIn Jobs",
            "url": "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}",
            "default": True,
        },
        "indeed": {
            "name": "Indeed",
            "url": "https://www.indeed.com/jobs?q={query}&l={location}",
        },
        "glassdoor": {
            "name": "Glassdoor",
            "url": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}&locT=C&locId=0",
        },
        "google": {
            "name": "Google Jobs",
            "url": "https://www.google.com/search?q={query}+jobs+{location}&ibp=htl;jobs",
        },
        "monster": {
            "name": "Monster",
            "url": "https://www.monster.com/jobs/search?q={query}&where={location}",
        },
        "wellfound": {
            "name": "Wellfound (AngelList)",
            "url": "https://wellfound.com/jobs?q={query}",
        },
        "dice": {
            "name": "Dice (Tech)",
            "url": "https://www.dice.com/jobs?q={query}&location={location}",
        },
    }
    
    def __init__(self, default_location: str = ""):
        self.default_location = default_location
    
    def search(
        self,
        query: str,
        platform: str = "linkedin",
        location: Optional[str] = None,
    ) -> bool:
        """
        Open a job search in the browser.
        
        Args:
            query: Job title/role to search for
            platform: Which platform to search on
            location: Location filter (optional)
            
        Returns:
            True if search was opened successfully
        """
        platform = platform.lower()
        
        if platform not in self.PLATFORMS:
            logger.warning(f"Unknown platform: {platform}, using LinkedIn")
            platform = "linkedin"
        
        loc = location or self.default_location
        url_template = self.PLATFORMS[platform]["url"]
        
        # URL encode the query and location
        search_url = url_template.format(
            query=quote_plus(query),
            location=quote_plus(loc),
        )
        
        try:
            webbrowser.open(search_url)
            logger.info(f"Opened job search: {query} on {platform}")
            return True
        except Exception as e:
            logger.error(f"Failed to open job search: {e}")
            return False
    
    def search_all(self, query: str, location: Optional[str] = None) -> List[str]:
        """
        Open job search on multiple platforms.
        
        Args:
            query: Job title/role to search for
            location: Location filter
            
        Returns:
            List of platforms where search was opened
        """
        opened = []
        for platform in ["linkedin", "indeed", "google"]:
            if self.search(query, platform, location):
                opened.append(platform)
        return opened
    
    def get_search_url(
        self,
        query: str,
        platform: str = "linkedin",
        location: Optional[str] = None,
    ) -> str:
        """Get the search URL without opening it."""
        platform = platform.lower()
        if platform not in self.PLATFORMS:
            platform = "linkedin"
        
        loc = location or self.default_location
        url_template = self.PLATFORMS[platform]["url"]
        
        return url_template.format(
            query=quote_plus(query),
            location=quote_plus(loc),
        )
    
    def get_platforms(self) -> Dict[str, str]:
        """Get available platforms and their names."""
        return {k: v["name"] for k, v in self.PLATFORMS.items()}
    
    @staticmethod
    def parse_job_query(text: str) -> tuple:
        """
        Parse a natural language job query.
        
        Args:
            text: Natural language query like "data science jobs in new york"
            
        Returns:
            Tuple of (role, location)
        """
        text = text.lower()
        
        # Remove common words
        for word in ["search for", "find", "look for", "jobs", "job", "positions", "roles"]:
            text = text.replace(word, "")
        
        # Try to find location
        location = ""
        location_keywords = ["in", "at", "near", "around"]
        
        for keyword in location_keywords:
            if f" {keyword} " in text:
                parts = text.split(f" {keyword} ", 1)
                text = parts[0]
                if len(parts) > 1:
                    location = parts[1].strip()
                break
        
        role = text.strip()
        
        return role, location

