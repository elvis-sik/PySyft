# stdlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

# third party
from pydantic import BaseModel
from pydantic import model_validator

SOCKET_TIMEOUT = 5  # seconds


class SMTPClient(BaseModel):
    server: str
    port: int
    password: str | None = None
    username: str | None = None

    def send(self, sender: str, receiver: list[str], subject: str, body: str) -> None:
        if not (subject and body and receiver):
            raise ValueError("Subject, body, and recipient email(s) are required")

        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = ", ".join(receiver)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        try:
            with smtplib.SMTP(self.server, self.port, timeout=SOCKET_TIMEOUT) as server:
                server.ehlo()
                # if server.has_extn("STARTTLS"):
                #     server.starttls()
                #     server.ehlo()
                # server.login(self.username, self.password)
                text = msg.as_string()
                server.sendmail(sender, ", ".join(receiver), text)
        except Exception as e:
            print("got an exception", e)
        # TODO: Add error handling

    @classmethod
    def check_credentials(
        cls, server: str, port: int, username: str, password: str
    ) -> bool:
        """Check if the credentials are valid.

        Returns:
            bool: True if the credentials are valid, False otherwise.
        """
        try:
            with smtplib.SMTP(server, port, timeout=SOCKET_TIMEOUT) as smtp_server:
                smtp_server.ehlo()
                if smtp_server.has_extn("STARTTLS"):
                    smtp_server.starttls()
                    smtp_server.ehlo()
                smtp_server.login(username, password)
                return True
        except Exception as e:
            print(e)
            # raise SyftException(public_message=str(e))
