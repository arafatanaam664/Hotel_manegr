# -*- coding: utf-8 -*-
"""يجمع أجزاء المحتوى ويبني الملف الرئيسي PDF"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pdfbuilder
from content_part1 import BLOCKS_P1
from content_part2 import BLOCKS_P2
from content_part3 import BLOCKS_P3
from content_part4 import BLOCKS_P4
from content_part5 import BLOCKS_P5
from content_part6 import BLOCKS_P6

BLOCKS = BLOCKS_P1 + BLOCKS_P2 + BLOCKS_P3 + BLOCKS_P4 + BLOCKS_P5 + BLOCKS_P6

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else '/home/user/Hotel_manegr/study/HotelERP_Study_Package/01_MASTER_PDF/HotelERP_Master_Study.pdf'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pdfbuilder.build(out, BLOCKS)
