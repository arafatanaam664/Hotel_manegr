#!/usr/bin/env python3
"""يعرض رمز TOTP الحالي لمدير لوحة الشركة في بيئة المعاينة التطويرية فقط
(السر الإنمائي JBSWY3DPEHPK3PXP موثق في vendor/config.py — الإنتاج: تسجيل
خاص بكل مستخدم عبر شاشة اللوحة، ولا يُطبع السر أبداً)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))
import pyotp

secret = os.environ.get('VENDOR_ADMIN_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')
print(pyotp.TOTP(secret).now())
