"""
This module defines the `ProfileManager` class, responsible for managing user profiles
within the Honest0 application. Currently, it provides basic in-memory storage
and retrieval of profile data, including system prompts.
"""

class ProfileManager:
    """
    Manages user profiles, including system prompts and other profile-specific data.
    Currently, profiles are stored in-memory.
    """
    def __init__(self):
        """
        Initializes the ProfileManager with an empty dictionary to store profile data.
        """
        self.profile_data = {}

    def create_profile(self, system_prompt: str) -> dict:
        """
        Creates a new profile or updates an existing one with a given system prompt.

        Args:
            system_prompt (str): The system prompt to associate with the profile.

        Returns:
            dict: The updated profile data.
        """
        self.profile_data["system_prompt"] = system_prompt
        return self.profile_data

    def store_profile(self, profile_data: dict):
        """
        Stores the provided profile data.
        Currently, this method only stores the profile in memory.
        In a future implementation, this would handle persistent storage (e.g., to a file or database).

        Args:
            profile_data (dict): The profile data dictionary to store.
        """
        self.profile_data = profile_data
        print("Profile stored successfully") # Log to console for immediate feedback.

    def get_profile(self) -> dict:
        """
        Retrieves the currently stored profile data.

        Returns:
            dict: The current profile data.
        """
        return self.profile_data