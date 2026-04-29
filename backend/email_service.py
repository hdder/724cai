"""
邮件发送服务 - Zoho Mail SMTP
"""
import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Zoho Mail SMTP 配置（中国版）
SMTP_HOST = 'smtp.zoho.com.cn'
SMTP_PORT = 465
SMTP_USER = 'noreply@724caixun.com'
SMTP_PASSWORD = '1998113Yd2022.'


def send_verification_code(email, code):
    """
    发送验证码邮件

    Args:
        email: 用户邮箱
        code: 验证码

    Returns:
        bool: 发送成功返回True，失败返回False
    """
    try:
        # 创建邮件
        msg = MIMEText(f"您的验证码是：{code}，请勿回复", "plain", "utf-8")
        msg["From"] = SMTP_USER
        msg["To"] = email
        msg["Subject"] = "邮箱验证码"

        # 发送邮件
        logger.info(f"📧 正在通过 Zoho SMTP 发送邮件到 {email}...")

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, email, msg.as_string())

        logger.info(f"✅ 验证码邮件发送成功 - 邮箱: {email}")
        return True

    except Exception as e:
        logger.error(f"❌ 发送邮件时发生异常 - 邮箱: {email}, 错误: {str(e)}", exc_info=True)
        return False
