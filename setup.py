import os
import subprocess
import sys

def setup():
    print("🚀 Starting rapid setup...")
    
    # 1. Fix dependencies in pyproject.toml if needed
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "r") as f:
            content = f.read()
        if '"telegram>=0.0.1"' in content:
            print("📦 Removing conflicting telegram package...")
            content = content.replace('    "telegram>=0.0.1",\n', '')
            with open("pyproject.toml", "w") as f:
                f.write(content)

    # 2. Sync dependencies
    print("🔄 Syncing dependencies...")
    subprocess.run(["uv", "sync"], check=True)

    # 3. Environment check
    required_envs = ["TELEGRAM_TOKEN", "DATABASE_URL"]
    missing = [e for e in required_envs if not os.environ.get(e)]
    if missing:
        print(f"⚠️ Missing environment variables: {', '.join(missing)}")
    else:
        print("✅ Environment variables present.")

    print("✨ Setup complete! You can now run the bot.")

if __name__ == "__main__":
    setup()
