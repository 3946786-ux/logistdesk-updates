"""LogistDesk 1.0 RC2 — polished navy/graphite interface."""
STYLESHEET = r"""
QMainWindow, QDialog, QWidget#dialogContents { background: #111820; color: #e4ebf2; }
QWidget { color: #e4ebf2; font-family: 'Segoe UI'; font-size: 16px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #111820; border: none; }
QFrame#sidebar { background: #151e28; border: none; border-right: 1px solid #2a3644; }
QFrame#sidebar QLabel { color: #e4ebf2; background: transparent; }
QListWidget#navigation { background: transparent; color: #aebccc; border: none; outline: none; }
QListWidget#navigation::item { padding: 13px 14px; margin: 3px 8px; border-radius: 8px; }
QListWidget#navigation::item:hover { background: #233142; }
QListWidget#navigation::item:selected { background: #2c4660; color: #f3f8ff; font-weight: 600; }
QListWidget#routeResults { background: #1c2632; border: 1px solid #344354;
    border-radius: 9px; outline: none; padding: 4px; }
QListWidget#routeResults::item { padding: 8px 10px; border-bottom: 1px solid #2b3846;
    border-radius: 5px; }
QListWidget#routeResults::item:hover { background: #293a4d; }
QListWidget#routeResults::item:selected { background: #304c66; color: #f4f8fc; }
QFrame#surfaceCard, QFrame#callCard, QFrame#financeCard,
QFrame#routePreview, QFrame#dashboardCard, QFrame#detailCard {
    background: #1b2530; border: 1px solid #2c3a49; border-radius: 11px;
}
QFrame#dialogHeader { background: #19232e; border-bottom: 1px solid #2c3a49; }
QFrame#dialogFooter { background: #19232e; border-top: 1px solid #2c3a49; }
QLabel#sectionTitle { color: #f0f5fa; font-size: 18px; font-weight: 700; background: transparent; }
QLabel#muted { color: #9babbc; font-size: 14px; background: transparent; }
QLineEdit, QComboBox, QPlainTextEdit, QDateTimeEdit {
    background: #222f3d; border: 1px solid #354657; border-radius: 8px;
    padding: 7px 10px; color: #f0f5fa;
    selection-background-color: #456b8e; selection-color: #ffffff;
}
QLineEdit, QComboBox, QDateTimeEdit { min-height: 30px; }
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QDateTimeEdit:hover { border-color: #51667b; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QDateTimeEdit:focus {
    border: 1px solid #6d9bc1;
}
QLineEdit:read-only { background: #1b2530; color: #aab8c7; }
QComboBox::drop-down, QDateTimeEdit::drop-down { width: 26px; border: none; }
QComboBox::down-arrow { width: 8px; height: 8px; }
QComboBox QAbstractItemView, QListView { background: #213346; color: #f0f7ff; border: 1px solid #354657;
    outline: 0; padding: 5px; selection-background-color: #3d5b76; selection-color: #ffffff; }
QPushButton { background: #263443; border: 1px solid #3a4c5e; padding: 10px 13px;
    border-radius: 8px; font-weight: 500; color: #e4ebf2; }
QPushButton:hover { background: #314356; border-color: #53697e; }
QPushButton:pressed { background: #3a5065; }
QPushButton:disabled { color: #748494; background: #1b2530; border-color: #2a3745; }
QPushButton#primary { background: #426f96; color: #ffffff; border: 1px solid #5688b0; font-weight: 600; }
QPushButton#primary:hover { background: #4e80a9; }
QPushButton#danger { color: #f2a5a6; background: #362a31; border: 1px solid #70454d; }
QPushButton#danger:hover { background: #493038; }
QPushButton#pill { background: #253240; border: 1px solid #354657;
    border-radius: 8px; padding: 8px 11px; color: #b7c7d7; }
QPushButton#pill:hover { background: #2e4052; }
QPushButton#pill:checked { background: #355674; border: 1px solid #6390b6; color: #f0f7ff; font-weight: 600; }
QToolButton#advancedToggle { background: transparent; border: none; padding: 10px;
    color: #a4c8e6; font-weight: 600; text-align: left; }
QToolButton#advancedToggle:hover { background: #243442; border-radius: 6px; }
QTableWidget { background: #1b2530; border: 1px solid #2c3a49; border-radius: 9px;
    gridline-color: transparent; alternate-background-color: #202c39; outline: 0; }
QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #293745; }
QTableWidget::item:selected { background: #34506a; color: #ffffff; }
QHeaderView::section { background: #24313f; color: #b4c4d3; padding: 10px 8px;
    border: none; border-bottom: 1px solid #344555; font-weight: 600; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; }
QStatusBar { background: #19232e; color: #a4b3c2; border-top: 1px solid #2c3a49; }
QMessageBox { background: #19232e; }
QMenu { background: #1c2733; color: #e4ebf2; border: 1px solid #344657; padding: 6px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: #34506a; }
QToolTip { background: #293a4c; color: #f1f6fa; border: 1px solid #52677a; padding: 6px; }
QSplitter::handle { background: #253341; }
QSplitter::handle:hover { background: #3c5870; }
QScrollBar:vertical { background: #18222d; width: 9px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: #455a6f; min-height: 38px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #6685a0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #18222d; height: 9px; margin: 0; border: none; }
QScrollBar::handle:horizontal { background: #455a6f; min-width: 38px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #6685a0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; border: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 0px; height: 0px; border: none; }
QCalendarWidget QWidget { background: #202d3a; color: #e4ebf2; }
QCalendarWidget QAbstractItemView { background: #202d3a; color: #e4ebf2;
    selection-background-color: #426f96; selection-color: white; }
/* LogistDesk 1.0: cohesive deep navy surfaces and restrained electric-blue accent. */
QMainWindow, QDialog, QWidget#dialogContents { background: #101923; color: #eaf1f8; }
QWidget { font-family: 'Segoe UI'; font-size: 16px; color: #eaf1f8; }
QFrame#sidebar { background: #111b27; border-right: 1px solid #26394b; }
QLabel#brandName { color: #f5f8fd; font-size: 20px; font-weight: 750; background: transparent; }
QLabel#brandCaption { color: #a9bbce; font-size: 12px; background: transparent; }
QLabel#navCaption { color: #758fa9; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#sidebarFooter { color: #8397ac; font-size: 12px; border-top: 1px solid #2a3b4b;
    padding-top: 13px; background: transparent; }
QListWidget#navigation { background: transparent; color: #b9c9d9; border: none; outline: 0; }
QListWidget#navigation::item { padding: 13px 12px; margin: 3px 0; border-radius: 9px; }
QListWidget#navigation::item:hover { background: #1e3042; }
QListWidget#navigation::item:selected { background: #294763; color: #ffffff; font-weight: 700;
    border-left: 3px solid #4d9cff; }
QFrame#surfaceCard, QFrame#callCard, QFrame#financeCard,
QFrame#routePreview, QFrame#dashboardCard, QFrame#detailCard {
    background: #172331; border: 1px solid #293c50; border-radius: 13px;
}
QLabel#sectionTitle { color: #f4f8fd; font-size: 19px; font-weight: 700; }
QLabel#muted { color: #a0b4c7; font-size: 14px; }
QLabel#documentBadge { color: #f2cb84; font-size: 14px; font-weight: 700; }
QLineEdit, QComboBox, QPlainTextEdit, QDateTimeEdit {
    background: #1e2d3d; color: #f2f7fc; border: 1px solid #344b60;
    border-radius: 9px; padding: 8px 10px;
    selection-background-color: #2b6fc0; selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QDateTimeEdit:focus {
    border: 1px solid #4e9bfb;
}
QPushButton { background: #25384b; color: #edf4fc; border: 1px solid #3b5269;
    border-radius: 9px; padding: 10px 13px; font-weight: 600; }
QPushButton:hover { background: #30475f; border-color: #64819d; }
QPushButton#primary { background: #2874dd; color: #ffffff; border: 1px solid #3989f3; font-weight: 700; }
QPushButton#primary:hover { background: #3686f2; border-color: #69a9ff; }
QPushButton#warning { background: #45371e; color: #ffda91; border: 1px solid #80602d; }
QPushButton#warning:hover { background: #5c4726; }
QPushButton#danger { background: #4a272d; color: #ffd1d4; border: 1px solid #8a454d; }
QPushButton#danger:hover { background: #653139; }
QPushButton:disabled { background: #1a2937; color: #6f879d; border-color: #283a4a; }
QTableWidget { background: #172331; alternate-background-color: #1b2b3a;
    border: 1px solid #2b4054; border-radius: 9px; outline: 0; }
QTableWidget::item { padding: 8px 9px; border-bottom: 1px solid #273b4e; }
QTableWidget::item:selected { background: #284c73; color: #ffffff; }
QHeaderView::section { background: #223448; color: #c5d6e7; padding: 11px 9px;
    border: none; border-bottom: 1px solid #354b61; font-weight: 700; }
QTabWidget#routeTabs::pane { border: none; background: #172331; top: -1px; }
QTabBar::tab { background: #1a2939; color: #aabed1; border: none;
    padding: 11px 15px; margin-right: 3px; border-top-left-radius: 8px;
    border-top-right-radius: 8px; }
QTabBar::tab:hover { background: #263e55; color: #edf5fc; }
QTabBar::tab:selected { background: #294a70; color: #ffffff;
    border-bottom: 2px solid #59a3ff; font-weight: 700; }
QPlainTextEdit#readOnlyCard { border: none; background: #172331; padding: 13px; }
QSplitter#mainSplitter::handle { background: #101923; width: 10px; }
QSplitter#mainSplitter::handle:hover { background: #355675; }
QStatusBar { background: #111c28; border-top: 1px solid #26394b; color: #a9bbcf; }
QMenu { background: #1c2b3b; border: 1px solid #3a526b; color: #edf4fc; }
QMenu::item:selected { background: #315b84; }
QScrollBar:vertical { background: #152230; width: 9px; border: none; }
QScrollBar::handle:vertical { background: #46617c; border-radius: 4px; min-height: 36px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
QScrollBar:horizontal { background: #152230; height: 9px; border: none; }
QScrollBar::handle:horizontal { background: #46617c; border-radius: 4px; min-width: 36px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }

/* RC2: polished reference-inspired visual system. Overrides RC1 rules above. */
QMainWindow, QDialog, QWidget#dialogContents { background-color: #0e1825; color: #eaf2fb; }
QWidget { color: #eaf2fb; font-family: 'Segoe UI'; font-size: 18px; }
QFrame#sidebar { background-color: #111e2d; border: none; border-right: 1px solid #294056; }
QFrame#sidebar QLabel { background: transparent; }
QLabel#brandName { color: #ffffff; font-size: 23px; font-weight: 750; }
QLabel#brandCaption { color: #b2c4d7; font-size: 13px; }
QLabel#navCaption { color: #8faac5; font-size: 12px; font-weight: 700; }
QLabel#sidebarFooter { color: #94aac1; font-size: 12px; border-top: 1px solid #30465c;
    padding-top: 14px; }
QLabel#pageCaption { color: #9fb4c8; font-size: 14px; }
QLabel#eyebrow { color: #93abc2; font-size: 12px; font-weight: 700; }
QLabel#routeHeading { color: #f5f9fe; font-size: 23px; font-weight: 750; }
QLabel#sectionTitle { color: #f6f9ff; font-size: 20px; font-weight: 700; }
QLabel#muted { color: #9eb4c9; font-size: 14px; }
QListWidget#navigation { background: transparent; color: #c5d4e4; border: none; outline: 0; font-size: 18px; }
QListWidget#navigation::item { padding: 12px 13px; margin: 3px 0; border-radius: 10px; }
QListWidget#navigation::item:hover { background: #23374b; color: #ffffff; }
QListWidget#navigation::item:selected { background: #2c4d70; color: #ffffff;
    border-left: 3px solid #62aeff; font-weight: 700; }
QFrame#surfaceCard, QFrame#callCard, QFrame#financeCard,
QFrame#routePreview, QFrame#dashboardCard, QFrame#detailCard {
    background: #182737; border: 1px solid #2d4257; border-radius: 14px;
}
QFrame#metricTile { background: #1e3042; border: 1px solid #354b61; border-radius: 10px; }
QLabel#metricCaption { color: #8eabc6; font-size: 11px; font-weight: 700; }
QLabel#metricValue { color: #f2f7ff; font-size: 15px; font-weight: 700; }
QLineEdit, QComboBox, QPlainTextEdit, QDateTimeEdit {
    background: #1d2e40; color: #f2f7ff; border: 1px solid #3a5168;
    border-radius: 9px; padding: 9px 12px; font-size: 17px;
    selection-background-color: #326db0; selection-color: white;
}
QLineEdit, QComboBox, QDateTimeEdit { min-height: 32px; }
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover { border-color: #66829d; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #67adfa; }
QLineEdit:read-only { background: #182737; color: #a7bdd2; }
QComboBox QAbstractItemView, QListView { background: #213346; color: #f0f7ff;
    border: 1px solid #4a627a; outline: 0; padding: 5px;
    selection-background-color: #335e87; selection-color: white; }
QPushButton { background: #293e53; color: #eff5fc; border: 1px solid #425c74;
    border-radius: 9px; padding: 11px 15px; min-height: 24px; font-size: 17px; font-weight: 600; }
QPushButton:hover { background: #35516b; border-color: #7693ae; }
QPushButton:pressed { background: #253d55; }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #368afa,stop:1 #246ed6); border: 1px solid #4998ff; color: white; font-weight: 700; }
QPushButton#primary:hover { background: #4596ff; border-color: #8dc2ff; }
QPushButton#warning { background: #51401e; color: #ffe3a5; border: 1px solid #987335; }
QPushButton#warning:hover { background: #68512a; }
QPushButton#danger { background: #572e36; color: #ffd5d8; border: 1px solid #a35c63; }
QPushButton#danger:hover { background: #71404a; }
QPushButton:disabled { background: #1b2a38; color: #70879d; border-color: #2c4052; }
QTableWidget { background: #182737; alternate-background-color: #1d2f41;
    border: 1px solid #30465b; border-radius: 9px; outline: 0; font-size: 17px; }
QTableWidget::item { padding: 9px 10px; border-bottom: 1px solid #2a4054; }
QTableWidget::item:selected { background: #31557b; color: #ffffff; }
QHeaderView::section { background: #22374b; color: #c5d8ea; padding: 12px 9px;
    border: none; border-bottom: 1px solid #3b546b; font-size: 14px; font-weight: 700; }
QTabWidget#routeTabs::pane { background: #182737; border: none; top: -1px; }
QTabBar::tab { background: #1d3042; color: #a8c0d6; border: none;
    padding: 12px 17px; margin-right: 3px; border-top-left-radius: 9px; border-top-right-radius: 9px; }
QTabBar::tab:hover { background: #2a4560; color: #f0f7ff; }
QTabBar::tab:selected { background: #31547a; color: white; font-weight: 700;
    border-bottom: 2px solid #67b0ff; }
QPlainTextEdit#readOnlyCard { background: #182737; border: none; padding: 14px; }
QSplitter#mainSplitter::handle { background: #0e1825; width: 10px; }
QSplitter#mainSplitter::handle:hover { background: #365c81; }
QStatusBar { background: #111e2c; border-top: 1px solid #294056; color: #a7c0d7; }
QMenu { background: #203247; color: #eff7ff; border: 1px solid #425d76; padding: 6px; }
QMenu::item { padding: 10px 24px; border-radius: 6px; }
QMenu::item:selected { background: #365e86; }
QScrollBar:vertical { background: #152434; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #4b6885; border-radius: 5px; min-height: 38px; }
QScrollBar::handle:vertical:hover { background: #6c91b4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
QScrollBar:horizontal { background: #152434; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #4b6885; border-radius: 5px; min-width: 38px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }
QToolTip { background: #2c4560; color: #ffffff; border: 1px solid #6383a1; padding: 7px; }
QMessageBox { background: #182737; }

"""

# Applied explicitly to standalone QCompleter popup windows as well as combobox lists.
POPUP_STYLESHEET = """
QAbstractItemView, QListView { background-color: #222f3d; color: #f0f5fa;
    border: 1px solid #45596d; outline: none; padding: 4px; font-size: 17px; }
QAbstractItemView::item, QListView::item { background: #222f3d; color: #f0f5fa;
    min-height: 29px; padding: 5px 8px; }
QAbstractItemView::item:hover, QListView::item:hover { background: #30475c; color: #ffffff; }
QAbstractItemView::item:selected, QListView::item:selected { background: #3d5b76; color: #ffffff; }
"""


# Route closing is a deliberate, high-visibility workflow action.
STYLESHEET += r"""
QPushButton#newRoute {
    background: #6c4fd3; color: #ffffff; border: 1px solid #8b73e5;
    border-radius: 9px; padding: 11px 15px; min-height: 24px;
    font-size: 16px; font-weight: 700;
}
QPushButton#newRoute:hover { background: #7a5de0; border-color: #aa98f0; }
QPushButton#newRoute:pressed { background: #5b41b8; }

QPushButton#routeClose {
    background: #238652; color: #ffffff; border: 1px solid #43ad73;
    border-radius: 9px; padding: 11px 15px; min-height: 24px;
    font-size: 17px; font-weight: 750;
}
QPushButton#routeClose:hover { background: #2c9c61; border-color: #67c78f; }
QPushButton#routeClose:pressed { background: #1b6f43; }
QPushButton#routeClose:disabled { background: #29443a; color: #718d81; border-color: #36584a; }
"""
