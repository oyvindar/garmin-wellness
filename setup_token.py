"""One-time setup. Run this on your own laptop, not in GitHub.

It logs in to Garmin Connect (asks for email, password and an MFA code if you
use one), then saves the login tokens encrypted to state/tokens.enc and prints
the key you paste into the GitHub secret GARMIN_TOKEN_KEY.
Your password is never stored anywhere.
"""
import getpass
from pathlib import Path

from cryptography.fernet import Fernet
from garminconnect import Garmin

STATE = Path(__file__).parent / "state" / "tokens.enc"


def main() -> None:
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (not shown): ")
    g = Garmin(email, password, return_on_mfa=True)
    status, state = g.login()
    if status == "needs_mfa":
        code = input("MFA code from Garmin (email/app): ").strip()
        g.resume_login(state, code)
    print(f"Logged in as {g.get_full_name()}")

    key = Fernet.generate_key()
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_bytes(Fernet(key).encrypt(g.client.dumps().encode()))
    print("\nSaved encrypted tokens to", STATE)
    print("\nAdd this as a repository secret named GARMIN_TOKEN_KEY")
    print("(GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret):\n")
    print(key.decode())
    print("\nThen commit and push state/tokens.enc.")


if __name__ == "__main__":
    main()
