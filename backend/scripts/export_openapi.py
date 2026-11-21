import argparse
import json
import secrets
from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the frontend API contract without credentials"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    )
    args = parser.parse_args()
    app = create_app(
        Settings(
            environment="test",
            database_url=SecretStr("sqlite://"),
            jwt_secret=SecretStr(secrets.token_urlsafe(48)),
            _env_file=None,  # type: ignore[call-arg]
        )
    )
    try:
        args.output.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    finally:
        app.state.engine.dispose()
    print(f"Exported {args.output}")


if __name__ == "__main__":
    main()
