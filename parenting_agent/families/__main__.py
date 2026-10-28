"""python -m parenting_agent.families {run,invite,check} [--keys-env FILE]

run     the families bot on Telegram (TELEGRAM_FAMILIES_BOT_TOKEN), long polling, reminders and summaries.
invite  print new single-use invite codes for new families. --internal marks Gonza's own test accounts.
check   load the settings, scrub the environment and print what the service would run with. No network.

Before anything starts, every variable that could reach the house is removed from the environment. --keys-env reads
only the brain key and the families bot token from an env file and ignores every other line.
"""
import argparse
import os
import sys
import time

from . import settings as settings_mod


def prepare(args):
    if settings_mod.same_bot_as_family(os.environ):
        raise SystemExit("TELEGRAM_FAMILIES_BOT_TOKEN is the family bot's token. Use the second bot.")
    removed = settings_mod.scrub_environment()
    if removed:
        print(f"removed {len(removed)} variables that could reach the house or hold secrets: {', '.join(removed)}", flush=True)
    if getattr(args, "keys_env", None):
        settings_mod.read_keys(args.keys_env)
    settings = settings_mod.load()
    os.environ["TZ"] = settings["tz"]
    time.tzset()
    return settings


def run(settings):
    from ..channels.telegram import TelegramMessenger
    from .bot import FamiliesBot
    from .service import Families
    messenger = TelegramMessenger(os.environ.get(settings_mod.BOT_TOKEN, ""))
    if messenger.me() == settings_mod.FAMILY_BOT_USERNAME:
        raise SystemExit("this token belongs to the family bot. Use the second bot.")
    service = Families(settings)
    bot = FamiliesBot(service, messenger, settings["poll_timeout_s"], settings["tick_s"])
    print(f"families: brain {settings['brain_name']} ({service.brain.destination}), {service.store.family_count()} families, "
          f"cap ${settings['daily_usd_cap']:.2f} a day", flush=True)
    try:
        bot.run()
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop()
        service.close()
    return 0


def invite(settings, count, internal):
    from .store import Store
    store = Store(settings["data_dir"])
    user = settings["bot_username"]
    try:
        for _ in range(count):
            code = store.create_invite(None, settings["invite_days"], internal=internal)
            print(code + (f"  https://t.me/{user}?start={code}" if user else ""))
        print(f"valid {settings['invite_days']} days, one family each{', internal test accounts' if internal else ''}. "
              f"{store.open_invites()} unused codes open.", file=sys.stderr)
    finally:
        store.close()
    return 0


def check(settings):
    from .store import Store
    store = Store(settings["data_dir"])
    try:
        print(f"brain {settings['brain_name']} {settings['brain'].get('model', '')}, data {settings['data_dir']}, tz {settings['tz']}")
        print(f"families {store.family_count()} of {settings['max_families']}, open invites {store.open_invites()}")
        print(f"caps: {settings['max_messages_per_family_day']} messages a family a day, "
              f"${settings['family_daily_usd']:.2f} a family a day, ${settings['daily_usd_cap']:.2f} in total a day")
        print(f"bot token {'set' if os.environ.get(settings_mod.BOT_TOKEN) else 'missing'}, "
              f"internal test accounts {len(settings['internal_user_ids'])}")
    finally:
        store.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="parenting agent for invited families")
    parser.add_argument("command", choices=["run", "invite", "check"])
    parser.add_argument("--keys-env", help="env file to read the brain key and the families bot token from")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--internal", action="store_true", help="invite for Gonza's own test accounts")
    args = parser.parse_args(argv)
    settings = prepare(args)
    if args.command == "invite":
        return invite(settings, max(1, min(args.count, 20)), args.internal)
    if args.command == "check":
        return check(settings)
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
