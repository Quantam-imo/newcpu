import datetime


class SessionBias:

	def get_session(self):
		hour = datetime.datetime.utcnow().hour

		if 7 <= hour <= 12:
			return "LONDON"

		if 13 <= hour <= 18:
			return "NY"

		return "ASIA"

	def get_session_weight(self):
		session = self.get_session()

		# London 7–12 UTC
		if session == "LONDON":
			return 1.2

		# NY 13–18 UTC
		if session == "NY":
			return 1.3

		# Asia
		return 0.8
