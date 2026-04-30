from TelegramBot.bot_service import TelegramBotService, service_from_env


class ServiceSystem:
	"""Keeps Orbitron services running."""

	def __init__(self) -> None:
		self.telegram: TelegramBotService = service_from_env()

	def run_forever(self) -> None:
		self.telegram.run_forever()
