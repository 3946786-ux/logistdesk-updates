"""Scoped trips styling, leaving dialogs and other pages on their existing theme."""
TRIPS_STYLE = r'''
QWidget { font-size: 15px; color: #eaf2fb; }
QLabel#tripsPageTitle { font-size: 30px; font-weight: 700; }
QLabel#summaryValue { font-size: 24px; font-weight: 700; }
QPushButton#summaryTile QLabel { background: transparent; }
QFrame#sidebar { background: #071522; border-right: 1px solid #233e54; }
QLabel#brandName { font-size: 22px; }
QLabel#brandCaption, QLabel#sidebarFooter { font-size: 13px; }
QListWidget#navigation { font-size: 16px; }
QListWidget#navigation::item:selected { background: #09315a; border-left: 3px solid #008aff; }
QLabel#pageCaption, QLabel#muted, QLabel#eyebrow { font-size: 14px; color: #a7bfd7; }
QLabel#routeHeading { font-size: 22px; font-weight: 700; }
QLabel#sectionTitle { font-size: 19px; }
QFrame#surfaceCard, QFrame#detailCard { background: #091a29; border: 1px solid #27465e; border-radius: 10px; }
QFrame#metricTile { background: #10263a; border: 1px solid #2b4d68; border-radius: 8px; }
QLabel#metricCaption { font-size: 13px; color: #abc4dc; }
QLabel#metricValue { font-size: 15px; }
QLabel#routeDataWarning { background: #47371e; color: #ffe0a0;
    border: 1px solid #9a7133; border-radius: 7px; padding: 8px 10px;
    font-size: 14px; }
QWidget#statusChips { background: transparent; border: none; }
QPushButton { font-size: 15px; padding: 8px 10px; min-height: 22px; background: #172f45; border: 1px solid #30546f; border-radius: 7px; }
QPushButton#primary { background: #007ef0; border: 1px solid #1699ff; }
QPushButton#newRoute { background: #6c4fd3; color: #ffffff; border: 1px solid #8b73e5; font-weight: 700; }
QPushButton#newRoute:hover { background: #7a5de0; border-color: #aa98f0; }
QPushButton#newRoute:pressed { background: #5b41b8; }
QPushButton#routeClose { background: #238652; color: #ffffff; border: 1px solid #43ad73; font-weight: 700; }
QPushButton#routeClose:hover { background: #2c9c61; border-color: #67c78f; }
QPushButton#routeClose:pressed { background: #1b6f43; }
QPushButton#routeClose:disabled { background: #29443a; color: #718d81; border-color: #36584a; }
QPushButton#warning { background: #534016; border-color: #bc8524; }
QPushButton#danger { background: #511e27; border-color: #9c3947; }
QPushButton#summaryTile { background: #102335; font-size: 16px; text-align: left; padding: 0; min-height: 76px; }
QPushButton#summaryTile:checked { background: #0b3156; border: 1px solid #008eff; }
QPushButton#summaryTile:hover { background: #173750; }
QLineEdit, QPlainTextEdit { font-size: 15px; background: #10263a; border: 1px solid #2b4c66; padding: 7px 9px; }
QLineEdit { min-height: 24px; }
QTableWidget { font-size: 15px; background: #091b2a; alternate-background-color: #0c2031; border: 1px solid #254258; }
QTableWidget::item { padding: 5px 7px; border-bottom: 1px solid #20394d; }
QTableWidget::item:selected { background: #144675; color: white; }
QHeaderView::section { font-size: 14px; background: #10273b; padding: 9px 6px; color: #b5d0e9; }
QTabWidget#routeTabs::pane { background: #091a29; border: none; }
QTabBar::tab { font-size: 14px; background: #102538; padding: 10px 10px; }
QTabBar::tab:selected { background: #104b7a; border-bottom: 2px solid #008eff; }
QPlainTextEdit#readOnlyCard { background: #091a29; padding: 10px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #091a29; border: none; }
QSplitter#mainSplitter::handle { background: #0e1825; width: 10px; }
QPushButton#reminderLink { background: transparent; border: none; padding: 0; }
'''
