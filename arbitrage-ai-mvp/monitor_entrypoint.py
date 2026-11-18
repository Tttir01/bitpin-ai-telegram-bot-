"""Run the paper monitor and fail CI when Telegram delivery fails.

The monitor intentionally catches delivery exceptions to finish its state write.
This entrypoint remembers those failures and returns a non-zero exit code so the
workflow's failure-notification step can run.
"""
import os

import monitor


def run():
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN; monitor was not started.")
    if not os.getenv("TELEGRAM_CHAT_ID", "").strip():
        raise SystemExit("Missing TELEGRAM_CHAT_ID; monitor was not started.")

    original_send = monitor.send_telegram
    delivery_errors = []

    def tracked_send(message):
        try:
            delivered = original_send(message)
        except Exception as error:
            delivery_errors.append(type(error).__name__)
            raise
        if not delivered:
            delivery_errors.append("message_not_delivered")
        return delivered

    monitor.send_telegram = tracked_send
    try:
        monitor.main()
    finally:
        monitor.send_telegram = original_send

    if delivery_errors:
        kinds = ", ".join(delivery_errors[:5])
        raise RuntimeError(
            f"Telegram delivery failed for {len(delivery_errors)} notification(s): {kinds}"
        )


if __name__ == "__main__":
    run()
