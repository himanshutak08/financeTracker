"""Constants for the Finance Tracker integration."""

DOMAIN = "finance_tracker"
PLATFORMS: list[str] = []
STORAGE_KEY = "storage"
SERVICES_KEY = "services"
DB_RELATIVE_PATH = "finance/tracker.db"

SERVICE_ADD_EXPENSE = "add_expense"
SERVICE_UPDATE_EXPENSE = "update_expense"
SERVICE_GENERATE_YEAR = "generate_year"
SERVICE_MARK_PAID = "mark_paid"
