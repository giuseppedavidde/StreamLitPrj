import os
from github import Github, GithubException

class CloudManager:
    """Manages cloud data synchronization using PyGithub."""
    
    REPO_NAME = "giuseppedavidde/Data_for_Analysis"
    FILE_PATH = "Crypto_Portfolio_csv.csv"

    def __init__(self, token):
        self.gh = Github(token)

    def fetch_portfolio_data(self):
        """
        Fetches the portfolio CSV content from the repository.
        Returns the content as bytes if successful, or None if failed.
        
        Returns:
            tuple: (Success, Content/Message)
            - If Success=True: Content is valid bytes or str.
            - If Success=False: Content is the error message.
        """
        try:
            repo = self.gh.get_repo(self.REPO_NAME)
            contents = repo.get_contents(self.FILE_PATH)
            
            # Return decoded content directly (bytes/str)
            return True, contents.decoded_content
            
        except GithubException as e:
            return False, f"GitHub Error: {e.status} - {e.data.get('message', '')}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def upload_portfolio_data(self, content, commit_message="Update Crypto Portfolio"):
        """
        Uploads the content to GitHub (Update or Create).
        """
        try:
            repo = self.gh.get_repo(self.REPO_NAME)
            
            if content is None:
                return False, "No content to upload."

            try:
                # Try to get existing file to update it
                contents = repo.get_contents(self.FILE_PATH)
                repo.update_file(contents.path, commit_message, content, contents.sha)
                return True, "File updated successfully."
            except GithubException as e:
                if e.status == 404:
                    # File doesn't exist, create it
                    repo.create_file(self.FILE_PATH, commit_message, content)
                    return True, "File created successfully."
                else:
                    raise e
                    
        except GithubException as e:
            return False, f"GitHub Error: {e.status} - {e.data.get('message', '')}"
        except Exception as e:
            return False, f"Error: {str(e)}"
