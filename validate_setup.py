import os
import json

BASE = os.path.dirname(os.path.abspath(__file__))

def check(label, passed, reason=""):
    status = "PASS" if passed else "FAIL"
    msg = f"[{status}] {label}"
    if not passed and reason:
        msg += f" — {reason}"
    print(msg)
    return passed

def main():
    all_pass = True

    # Folder checks
    folders = [
        "data/inputs",
        "data/drafts",
        "data/sent",
        "data/parsed",
        "data/runs",
        "modules",
    ]
    for folder in folders:
        path = os.path.join(BASE, folder)
        ok = os.path.isdir(path)
        all_pass &= check(f"Folder exists: {folder}", ok, f"{path} not found")

    # .env exists and has required keys
    env_path = os.path.join(BASE, ".env")
    env_exists = os.path.isfile(env_path)
    all_pass &= check(".env exists", env_exists, f"{env_path} not found")

    if env_exists:
        env_vars = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()

        for key in ("GROQ_API_KEY", "TAVILY_API_KEY"):
            ok = key in env_vars and bool(env_vars[key])
            all_pass &= check(f".env has {key}", ok, f"{key} missing or empty in .env")

    # credentials.json exists
    creds_path = os.path.join(BASE, "credentials.json")
    ok = os.path.isfile(creds_path)
    all_pass &= check("credentials.json exists", ok, f"{creds_path} not found")

    # test_org.json is valid JSON with required fields
    input_path = os.path.join(BASE, "data/inputs/test_org.json")
    input_exists = os.path.isfile(input_path)
    all_pass &= check("data/inputs/test_org.json exists", input_exists, f"{input_path} not found")

    if input_exists:
        try:
            with open(input_path) as f:
                data = json.load(f)
            all_pass &= check("test_org.json is valid JSON", True)
            for field in ("org", "email", "goal"):
                ok = field in data and bool(data[field])
                all_pass &= check(f"test_org.json has field: {field}", ok, f"'{field}' missing or empty")
        except json.JSONDecodeError as e:
            all_pass &= check("test_org.json is valid JSON", False, str(e))

    print()
    print("=" * 40)
    print("Setup validation:", "ALL PASS" if all_pass else "SOME CHECKS FAILED")

if __name__ == "__main__":
    main()
