"""Main entry point for {{PROJECT_NAME}}."""

import os

from dotenv import load_dotenv


def main() -> None:
    """Main entry point."""
    load_dotenv()

    print(f"Hello from {{PROJECT_NAME}}!")
    print(f"Environment: {os.getenv('ENV', 'development')}")


if __name__ == "__main__":
    main()
