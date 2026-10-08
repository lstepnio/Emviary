import argparse
import json
import logging
import os
import re
from pathlib import Path

from .service import Service
from .settings import FramePolicy, cron_for


def private_file(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(value)


def main():
    parser = argparse.ArgumentParser(description="Owner operations for the bird-art frame")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=int(os.getenv("EMVIARY_PORT", "8080")))
    add = commands.add_parser("add-frame")
    add.add_argument("id")
    add.add_argument("--site", default=None)
    add.add_argument("--token-file", required=True)
    rotate = commands.add_parser("rotate-token")
    rotate.add_argument("id")
    rotate.add_argument("--token-file", required=True)
    policy = commands.add_parser("set-frame")
    policy.add_argument("id")
    policy.add_argument("--wake")
    policy.add_argument("--preset", choices=["balanced", "dynamic", "vivid", "soft"])
    policy.add_argument("--labels", choices=["on", "off"])
    policy.add_argument("--weather-cues", choices=["on", "off"])
    policy.add_argument("--max-birds", type=int, choices=[1, 2, 3])
    prepare = commands.add_parser("prepare")
    prepare.add_argument("id")
    prepare.add_argument("--date")
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--offline", action="store_true")
    commands.add_parser("status")
    owner = commands.add_parser("init-owner")
    owner.add_argument("--password-file", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output")
    provision = commands.add_parser("provision")
    provision.add_argument("id")
    provision.add_argument("--token-file", required=True)
    provision.add_argument("--output", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "emviary.api:create_app",
            host=args.host,
            port=args.port,
            factory=True,
            workers=1,
            access_log=False,
        )
        return
    service = Service()
    try:
        if args.command in ("add-frame", "rotate-token"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", args.id):
                raise ValueError("Frame ID must contain lowercase letters, digits, and hyphens")
            path = Path(args.token_file)
            # Reserve the output before changing authentication state.
            private_file(path, "")
            try:
                if args.command == "add-frame":
                    policy = service.settings.config.frame_defaults.model_copy()
                    if args.site:
                        service.settings.config.site(args.site)
                        policy.site_id = args.site
                    token = service.store.add_frame(args.id, policy)
                else:
                    token = service.store.rotate_token(args.id)
                path.write_text(token + "\n")
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            result = {"frame": args.id, "token_file": str(path), "token_printed": False}
        elif args.command == "set-frame":
            data = json.loads(service.store.frame(args.id)["policy"])
            if args.wake:
                data.update(wake_local_time=args.wake, firmware_rotate_cron=cron_for(args.wake))
            if args.preset:
                data["processing_preset"] = args.preset
            if args.labels:
                data["show_species_name"] = args.labels == "on"
            if args.weather_cues:
                data["weather_cues"] = args.weather_cues == "on"
            if args.max_birds:
                data["max_birds"] = args.max_birds
            service.store.set_policy(args.id, FramePolicy.model_validate(data))
            result = {"frame": args.id, "configuration": "updated"}
        elif args.command == "prepare":
            image = service.prepare(args.id, args.date, force=args.force, offline=args.offline)
            result = {
                "frame": args.id,
                "date": image["local_date"],
                "revision": image["revision"],
                "artwork": image["artwork_id"],
                "path": image["path"],
                "sha256": image["body_hash"],
            }
        elif args.command == "init-owner":
            import secrets

            from .owner import secret_directory, set_password

            if (secret_directory() / "owner-auth.json").exists():
                raise ValueError("Owner password already initialized")
            password = secrets.token_urlsafe(24)
            private_file(args.password_file, password + "\n")
            set_password(password)
            result = {"owner_password_file": args.password_file, "password_printed": False}
        elif args.command == "status":
            result = service.status()
        elif args.command == "backup":
            result = {"backup": service.backup(args.output)}
        else:
            frame = service.store.frame(args.id)
            from .api import config_payload

            config = json.loads(config_payload(frame))["config"]
            token = Path(args.token_file).read_text().strip()
            identity = service.store.authenticate(token)
            if identity is None or identity["id"] != args.id:
                raise ValueError("Token does not belong to this frame")
            config["image_url"] = service.settings.config.public_base_url + "/v1/image"
            config["access_token"] = token
            private_file(args.output, json.dumps(config, indent=2) + "\n")
            result = {"frame": args.id, "private_configuration_file": args.output}
        print(json.dumps(result, indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
