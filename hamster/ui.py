from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


console = Console()


HAMSTER_LOGO = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠞⡄⠀⣀⢢⡖⣴⢲⡀⠀⠀⠴⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡶⣏⢷⣺⡱⢧⣛⡵⣠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣀⣠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠐⣮⡕⠮⢳⠶⣭⢳⡽⡸⣇⡖⠀⢀⣀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣸⣿⣿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠐⠀⢨⢳⠞⣡⢬⡙⠮⢓⡄⠳⣭⢎⠀⠐⠋⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢀⣰⣶⣘⣿⣿⣿⣿⣿⣿⣇⣠⣴⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠨⢟⡼⣓⢮⡳⢏⡾⣹⠎⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⣀⣸⣿⣿⣿⣿⡿⢿⣿⣿⣿⣿⣿⣿⣿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠉⠸⢹⢶⢹⡉⠶⠁⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠟⠛⡟⣯⠛⠃⢻⣏⠾⣽⢣⡏⠛⠙⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠛⠀⠀⠀⠉⠈⠁⠉⠀⠀⠀⠙⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⡀⠀⠀⠀⠀⠀⢀⡀⠀⢀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣿⠛⠛⣿⣿⣤⠀⠀⣄⣄⣾⣷⣾⡟⠀⠀⠀⠀⠀⣤⣿⣿⡛⣛⣿⡤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⡟⡱⡝⠆⢸⣿⣿⣾⣿⣿⣿⣿⣿⣿⡇⢀⣤⣾⣿⣷⣾⣿⡇⠰⣣⢎⣿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣷⡳⢉⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣿⣿⣿⣿⣿⣿⣿⣿⣶⡁⢯⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢛⣷⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣞⠙⠀⠀⠀⠀⠀⠀⢀⣰⣿⣿⣖⡀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⣥⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣦⣿⣿⣿⣿⣿⣿⣖⠀⠀⠀⠀⢠⣴⣤⣿⡿⣿⣿⢷⣧⡄⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⡟⠀⠤⢻⣿⣿⣿⣿⣿⣿⣿⣿⡿⠥⠀⠙⣿⣿⣿⣿⣿⣿⣇⠀⠀⠀⠈⠉⠙⠂⠙⠑⠋⠁⠁⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣿⣿⣿⠋⡭⣉⢃⠀⠀⣹⣿⣿⠻⠧⠸⠿⣿⣿⣯⡀⠀⢀⠫⣩⠝⢿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿⣿⣇⠻⡔⢥⣋⣿⣿⣿⣿⣿⣷⡿⣿⣿⣿⣿⣿⣿⣿⠈⣇⠎⣜⡂⣿⣿⣿⣧⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣮⣼⣧⣾⣿⣿⡟⢿⠏⡉⣂⢦⡉⡉⡛⡛⣿⣿⣿⣮⣽⣦⣾⣿⣿⣿⣿⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣿⣿⣿⣿⣿⣿⣿⠏⡁⢯⡖⡦⢝⠮⣥⢺⡵⠃⠉⠽⣿⣿⣿⣿⣿⣿⣿⡿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢿⣿⣿⣿⣿⣿⣿⣿⣇⠢⣜⠶⡙⠈⠀⠀⠈⠀⢵⢫⣏⠓⣸⣿⣿⣿⣿⣿⣿⣷⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⡧⢀⡬⢯⡁⠀⠀⠀⠀⠀⢨⢳⢦⡁⢼⣿⣿⣿⣿⣿⣿⣿⣇⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⣿⣿⣧⣆⡍⡈⣱⢲⠤⠀⠀⠀⡠⢶⡩⠌⢡⣴⣿⣿⣿⣿⣿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢹⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡀⠷⠏⡸⢹⢿⢸⡹⠈⠉⢰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⡋⠿⢿⣿⣿⣿⡷⡠⣅⠌⠃⢀⣌⠠⣿⣿⣿⣿⡿⢟⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⢿⣿⣷⣎⣉⡛⠛⠃⠑⠦⠁⠀⠐⠬⠓⠿⠟⢛⣨⣴⣾⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣿⣿⡟⢀⢦⢒⡌⢻⡿⠀⠤⠀⠄⠀⠀⠀⠀⢻⣽⣷⣿⣆⣿⢁⡔⣠⢂⢻⣿⣿⣿⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠩⣻⣿⣇⡐⣎⠡⡺⢅⢀⡠⠄⠁⠠⣀⣤⣇⠠⠈⢿⣿⣿⡿⢁⡺⡈⢱⠎⣸⣿⡿⡟⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠒⠛⠷⠌⠳⣙⠮⠸⠟⠿⠿⠯⠿⠿⠿⠦⠤⠾⠟⠿⠃⠼⡱⡭⠓⠴⠟⠋⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀"""

HAMSTER_EXIT_LOGO = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠘⢣⣆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣶⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣶⡿⣿⣤⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢘⡾⣥⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣤⣹⡿⣻⣿⣥⣤⡀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠐⠙⠒⠁⠉⠁⠀⠀⠀⠀⠀⠀⢂⡀⠀⢀⣠⠾⣽⠖⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠩⠻⠝⠚⠥⠻⠝⠯⠛⠛⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠝⠫⠏⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⡀⠀⠀⠀⠀⠀⠠⢤⡄⠠⣄⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⢊⣤⠆⡨⡑⡄⠀⢀⡀⠠⠬⠄⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⠄⠀⣃⣾⡇⠸⣰⢘⠸⢀⣐⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣴⡼⢿⠿⣦⣄⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⢠⣼⡿⣿⣦⣄⠀⠀⠀⠀⠀⠀⠠⠨⣀⣩⠀⠀⢨⣿⣿⣿⣿⣶⣿⣿⣶⣤⣭⡑⡒⠤⢀⡀⠀⠀⠀⠀⠈⠁⠛⠈⠋⠈⠉⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠁⠈⠓⠃⠀⠉⠁⠀⠀⡠⠀⠀⢌⣰⣿⣿⣷⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣭⠢⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⡰⠟⢿⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣌⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢄⢁⠆⢌⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢋⡟⡋⡍⣻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣄⠠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠢⡍⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣿⣧⣓⣘⣼⡿⣱⣿⣿⣿⣿⣿⣿⣿⣿⡆⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡇⢿⣿⣿⣿⡿⣿⣿⣟⠻⢟⣿⣿⣿⣿⡿⢫⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡘⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠜⢸⣿⠿⢋⢴⣿⣿⣴⣾⣿⣿⣿⣿⠇⢠⡙⠿⠿⢛⣽⣿⣿⣿⣿⣿⣿⣿⡇⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡇⢻⣿⡘⠣⣦⡿⠿⠛⠻⢿⣛⣿⣼⣆⡀⢁⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⠇⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢣⡑⢿⣿⣿⣿⣿⣿⠁⠮⠄⣿⣿⣿⠋⠁⡛⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢣⢡⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢤⣀⠖⡆⣖⠂⣀⠀⠀⠀⢸⠼⣿⣿⡟⢁⠠⡐⢿⣿⣿⡀⢈⡰⢄⢻⣿⣿⣿⣿⣿⣿⢟⡯⠁⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢖⡪⠈⠀⠀⠀⠋⢪⡤⡀⠈⠠⡉⢮⣛⢷⡀⠢⡜⣠⢙⢿⢿⣄⠓⠌⡰⢽⡛⡟⣯⢭⡞⠣⡡⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⡤⢥⠀⠀⠀⠀⠀⢥⠥⡀⠀⠀⠈⠢⢌⡃⠝⡲⢄⡁⣔⢫⠞⡴⢣⢞⡩⣇⢯⡙⠖⢋⡠⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠉⢠⠪⢠⠀⡤⡘⠦⠀⠀⠀⠀⠀⠀⠀⠈⠑⠐⠀⢌⡈⣁⢉⡈⣁⡈⣁⠀⠀⠔⠈⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀"""

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def print_logo() -> None:
    # ── Braille art rendered inside a high-contrast gold panel on startup ──
    logo_text = Text(HAMSTER_LOGO, style="bold gold3")
    console.print(
        Panel(
            Align.center(logo_text),
            border_style="gold3",
            padding=(0, 2),
            subtitle="[dim]🐹 Hamster — sandboxed OpenRouter engineering agent[/dim]",
        )
    )
    metrics = Table.grid(padding=(0, 2))
    metrics.add_column(style="bold white")
    metrics.add_column(style="dim")
    metrics.add_row("Tools", "search_codebase · read_file · edit_file_patch · web_search · run_sandbox_command")
    metrics.add_row("Boundary", "./sandbox only — absolute path containment enforced")
    metrics.add_row("Approval", "hard y/n gate before every tool call and network action")
    console.print(Panel(metrics, border_style="gold3", title="[bold gold3]Ready[/]", title_align="left"))


def print_exit_logo() -> None:
    # ── Running/waving exit Braille hamster rendered in a farewell panel ──
    exit_text = Text(HAMSTER_EXIT_LOGO, style="bold gold3")
    farewell = Text("Bye! 🐹", style="bold gold3")
    console.print(
        Panel(
            Align.center(
                Text.assemble(exit_text, Text("\n"), farewell)
            ),
            border_style="gold3",
            title="[bold gold3]See you soon[/]",
            padding=(0, 2),
        )
    )


def print_help() -> None:
    table = Table(title="[bold cyan]Hamster Commands[/]", border_style="cyan", box=box.ROUNDED)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Action", style="white")
    table.add_row("/help", "Show this command guide")
    table.add_row("/search <query>", "Ask Hamster to search technical documentation")
    table.add_row("/clear", "Clear the terminal and redraw the splash")
    table.add_row("/exit", "Leave Hamster (prints farewell graphic)")
    console.print(table)


def render_action_summary(action: str, details: Mapping[str, str]) -> None:
    table = Table(title="Requested Tool Action", border_style="magenta")
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white", overflow="fold")
    table.add_row("Action", action)
    for key, value in details.items():
        table.add_row(key, value)
    console.print(table)


def render_files_summary(rows: Sequence[Mapping[str, str]]) -> None:
    table = Table(title="Files Touched", border_style="cyan")
    table.add_column("Operation", style="bold")
    table.add_column("Path", style="white", overflow="fold")
    table.add_column("Scope", style="dim")
    for row in rows:
        table.add_row(row.get("operation", ""), row.get("path", ""), row.get("scope", "sandbox"))
    console.print(table)


def render_diff(filepath: str, diff_lines: Sequence[str]) -> None:
    # ── Tokenized color diff: additions=green, deletions=red, metadata=cyan ──
    additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++ "))
    deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("--- "))

    body = Text()
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++ "):
            body.append(line + "\n", style="bold green")
        elif line.startswith("-") and not line.startswith("--- "):
            body.append(line + "\n", style="bold red")
        elif line.startswith("@@") or line.startswith("--- ") or line.startswith("+++ "):
            # Boundary / hunk headers and file paths rendered in cyan
            body.append(line + "\n", style="bold cyan")
        else:
            body.append(line + "\n", style="white")

    meta = Text.assemble(
        (f"+{additions} addition{'s' if additions != 1 else ''}", "green"),
        ("  ", "white"),
        (f"-{deletions} deletion{'s' if deletions != 1 else ''}", "red"),
        ("  ", "white"),
        (f"[{filepath}]", "bold cyan"),
    )
    console.print(Rule(title=meta, style="cyan"))
    console.print(
        Panel(
            body,
            title="[bold cyan]Diff Preview[/]",
            subtitle=f"[dim cyan]{filepath}[/]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def render_security_violation(message: str) -> None:
    console.print(Panel(message, title="Security Violation", border_style="bold red", style="red"))


def render_tool_result(name: str, content: str) -> None:
    console.print(Panel(content, title=f"tool:{name}", border_style="green"))


def render_model_error(message: str) -> None:
    console.print(Panel(message, title="Model Error", border_style="red"))


def print_assistant_delta(text: str) -> None:
    console.print(text, end="", markup=False, highlight=False)


def prompt_user(prompt: str) -> str:
    return console.input(prompt)


def status(message: str):
    """Generic status spinner (used for local sandbox ops — fast, bright)."""
    return console.status(message, spinner="dots", spinner_style="gold3")


def remote_status(message: str):
    """Visually distinct spinner for remote OpenRouter API calls (slow network).

    Uses a slower 'earth' spinner and a muted blue style so operators can
    immediately distinguish remote model latency from rapid local sandbox ops.
    """
    return console.status(message, spinner="earth", spinner_style="steel_blue1")


def sandbox_status(message: str):
    """Explicit spinner for fast local sandbox operations (reads, patches, search).

    Uses the 'dots2' spinner and gold styling to signal an in-process,
    approval-gated sandbox action rather than a remote call.
    """
    return console.status(message, spinner="dots2", spinner_style="gold3")


def confirm(prompt: str) -> bool:
    while True:
        answer = prompt_user(f"[bold gold3]{prompt}[/] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("Please answer y or n.", style="yellow")
