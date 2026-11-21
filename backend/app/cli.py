import argparse
import getpass

from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import build_engine, session_factory
from app.schemas.auth import UserCreate
from app.services.auth import create_user


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit administrator bootstrap")
    parser.add_argument("command", choices=["create-admin"])
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    payload = UserCreate(user_id=args.user_id, password=SecretStr(password), role="admin")
    engine = build_engine(Settings())  # type: ignore[call-arg]
    try:
        with session_factory(engine).begin() as db:
            create_user(db, payload)
    except DomainError as exc:
        parser.exit(1, f"{exc.message}\n")
    finally:
        engine.dispose()
    print("Administrator created. Sign in with the specified user ID.")


if __name__ == "__main__":
    main()
