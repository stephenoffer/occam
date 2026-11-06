import smtplib


def notify(order, db):
    user = db.get_user(order.user_id)
    smtplib.SMTP("localhost").sendmail("noreply@example.invalid", user.email, f"Order {order.id}")
