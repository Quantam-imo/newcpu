class CapitalEngine:

    def __init__(self):
        self.withdraw_threshold = 52000
        self.last_withdrawal_balance = 50000

    def check_withdrawal(self, current_balance):

        if current_balance > self.withdraw_threshold:
            withdraw_amount = current_balance - self.withdraw_threshold
            return {
                "eligible": True,
                "withdraw_amount": withdraw_amount
            }

        return {
            "eligible": False,
            "withdraw_amount": 0
        }
