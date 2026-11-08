"""Entry point executed inside a disposable Microsandbox browser guest."""
import asyncio, base64, json, sys
from app.qa import scan

def main():
    task = json.loads(sys.argv[1])
    result, artifacts = asyncio.run(scan(
        str(task["target_url"]),
        str(task["run_id"]),
        str(task.get("depth", "standard")),
        task.get("workflow") or [],
    ))
    screenshots = {}
    for path, content_type in artifacts:
        if content_type == "image/png" and path.is_file():
            screenshots[path.name] = base64.b64encode(path.read_bytes()).decode("ascii")
    result["screenshots_base64"] = screenshots
    print(json.dumps(result, separators=(",", ":")))

if __name__ == "__main__":
    main()
