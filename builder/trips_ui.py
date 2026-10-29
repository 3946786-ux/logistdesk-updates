"""Presentation-only composition of the trips workspace; actions live in app.py."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QPlainTextEdit, QHeaderView, QSizePolicy,
    QLineEdit, QCheckBox,
)
from tracking import reminder_title, display_datetime
from trips_theme import TRIPS_STYLE
from PySide6.QtGui import QIcon
from pathlib import Path
from route_display import route_status_parts


_BADGE_COLORS = {
    'success': ('#153b31', '#a4e8c3', '#33795b'),
    'danger': ('#512b32', '#ffbdc2', '#96505a'),
    'warning': ('#4c3c1f', '#ffda91', '#987337'),
    'muted': ('#273d51', '#c6d8e9', '#46627d'),
}


def status_chips(route: dict, *, deleted_only: bool = False) -> QWidget:
    """Readable colored statuses without altering the stored status value."""
    holder = QWidget()
    holder.setObjectName('statusChips')
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(4, 3, 4, 3)
    layout.setSpacing(3)
    for text, kind in route_status_parts(route, deleted_only=deleted_only):
        background, foreground, border = _BADGE_COLORS[kind]
        chip = QLabel(text)
        chip.setObjectName('statusChip')
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chip.setStyleSheet(
            f'background: {background}; color: {foreground}; '
            f'border: 1px solid {border}; border-radius: 6px; '
            'padding: 3px 5px; font-size: 12px; font-weight: 700;'
        )
        layout.addWidget(chip)
    holder.setToolTip(' · '.join(text for text, _ in route_status_parts(route, deleted_only=deleted_only)))
    holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return holder


def build_trips(w, page, splitter, left_panel, details):
    w.route_filter = 'all'
    w.summary_buttons = {}
    w.summary_values = {}
    w.summary_icons = []
    w.summary_layout = QGridLayout()
    w.summary_layout.setSpacing(8)
    captions = [('all', 'Все рейсы'), ('search', 'В поиске'), ('agreed', 'Согласованы'),
                ('docs', 'Жду документы'), ('road', 'В пути'), ('closed', 'Закрытые'), ('archive', 'Архив')]
    for i, (key, caption) in enumerate(captions):
        button = QPushButton()
        button.setObjectName('summaryTile')
        button.setCheckable(True)
        button.setMinimumHeight(68)
        content = QHBoxLayout(button)
        content.setContentsMargins(10, 8, 10, 8)
        icon = QLabel()
        asset = {'all': 'routes', 'search': 'search', 'agreed': 'carriers', 'docs': 'card',
                 'road': 'routes', 'closed': 'today', 'archive': 'archive'}[key]
        icon.setPixmap(QIcon(str(Path(__file__).parent / 'assets' / f'nav_{asset}.png')).pixmap(28, 28))
        content.addWidget(icon)
        w.summary_icons.append(icon)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        label = QLabel(caption)
        label.setWordWrap(True)
        number = QLabel('0')
        number.setObjectName('summaryValue')
        if key in ('agreed', 'docs', 'search', 'road'):
            color = {'agreed': '#61d6a0', 'docs': '#f3c765', 'search': '#f3c765', 'road': '#74baff'}[key]
            number.setStyleSheet(f'color: {color};')
        texts.addWidget(label)
        texts.addWidget(number)
        content.addLayout(texts, 1)
        for child in (label, number, icon):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        w.summary_values[key] = number
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda checked=False, key=key: select_filter(w, key))
        button.setToolTip('Показать: ' + caption + '. Показатели могут пересекаться.')
        w.summary_buttons[key] = (button, caption)
        w.summary_layout.addWidget(button, 0, i)
    page.layout().insertLayout(0, w.summary_layout)
    w.page_title.setObjectName('tripsPageTitle')
    w.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    lp = QVBoxLayout(left_panel)
    lp.setContentsMargins(12, 12, 12, 12)
    lp.setSpacing(8)
    title = QLabel('Список рейсов')
    title.setObjectName('sectionTitle')
    lp.addWidget(title)
    search_row = QHBoxLayout()
    w.route_search = QLineEdit()
    w.route_search.textChanged.connect(w.refresh_routes)
    w.route_search.addAction(QIcon(str(Path(__file__).parent / 'assets' / 'nav_search.png')), QLineEdit.ActionPosition.LeadingPosition)
    w.route_search.setMinimumWidth(0)
    w.route_search.setPlaceholderText('Маршрут, груз, отправитель, ID…')
    w.route_search.setClearButtonEnabled(True)
    search_row.addWidget(w.route_search, 1)
    w.route_search.show()
    filters_button = QPushButton('Фильтры')
    filters_button.setCheckable(True)
    search_row.addWidget(filters_button)
    lp.addLayout(search_row)
    panel = QWidget()
    filters = QHBoxLayout(panel)
    filters.setContentsMargins(0, 0, 0, 0)
    w.show_closed = QCheckBox('Закрытые')
    w.show_closed.setChecked(True)
    w.show_archived = QCheckBox('С архивом')
    for checkbox in (w.show_closed, w.show_archived):
        filters.addWidget(checkbox)
        checkbox.toggled.connect(w.refresh_routes)
        checkbox.show()
    panel.hide()
    filters_button.toggled.connect(panel.setVisible)
    lp.addWidget(panel)
    w.route_count_label = QLabel()
    w.route_count_label.setObjectName('muted')
    lp.addWidget(w.route_count_label)
    w.route_count_label.show()
    w.routes_table = w.create_table(['ID', 'Маршрут', 'Груз', 'Вес', 'Загрузка', 'Статус'])
    w.routes_table.setObjectName('routesTable')
    w.routes_table.doubleClicked.connect(w.edit_route)
    w.routes_table.itemSelectionChanged.connect(w.refresh_route_details)
    header = w.routes_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    header.setMinimumSectionSize(52)
    header.setStretchLastSection(False)
    for col, width in ((0, 62), (1, 220), (2, 138), (3, 80), (4, 96), (5, 154)):
        w.routes_table.setColumnWidth(col, width)
    w.routes_table.verticalHeader().setDefaultSectionSize(62)
    w.routes_table.verticalHeader().setMinimumSectionSize(56)
    header.sectionResized.connect(lambda *_: w.routes_table.resizeRowsToContents())
    w.routes_table.setTextElideMode(Qt.TextElideMode.ElideNone)
    w.routes_table.setWordWrap(True)
    lp.addWidget(w.routes_table, 1)
    w.routes_table.show()
    w.route_open_button = QPushButton('Открыть выбранный рейс →')
    w.route_open_button.setObjectName('primary')
    w.route_open_button.clicked.connect(lambda: open_route_compact(w))
    w.route_open_button.hide()
    lp.addWidget(w.route_open_button)
    w.routes_table.itemClicked.connect(lambda _item: open_route_compact(w))
    left_panel.setMinimumWidth(395)

    box = details.layout()
    box.setContentsMargins(12, 12, 12, 12)
    box.setSpacing(8)
    w.route_back_button = QPushButton('← К списку рейсов')
    w.route_back_button.clicked.connect(lambda: back_to_routes(w))
    w.route_back_button.hide()
    box.insertWidget(0, w.route_back_button)
    w.route_tabs.setMinimumHeight(240)
    w.route_carriers_table.verticalHeader().setDefaultSectionSize(60)
    w.route_carriers_table.setColumnCount(5)
    w.route_carriers_table.setHorizontalHeaderLabels(['Перевозчик', 'Телефон', 'Машина', 'Ставка', 'Статус'])
    for col, width in ((1, 150), (2, 105), (3, 115), (4, 120)):
        w.route_carriers_table.setColumnWidth(col, width)
    w.route_carriers_table.setTextElideMode(Qt.TextElideMode.ElideNone)
    w.route_carriers_table.verticalHeader().setMinimumSectionSize(56)
    w.route_carriers_table.horizontalHeader().sectionResized.connect(lambda *_: w.route_carriers_table.resizeRowsToContents())
    w.route_add_carrier.setText('+ Перевозчик')
    w.route_add_carrier.setObjectName('primary')
    w.route_note = QPlainTextEdit()
    w.route_note.setReadOnly(True)
    w.route_note.setPlaceholderText('Заметки можно добавить при редактировании рейса.')
    w.route_reminder = QPushButton('Нет активных\nнапоминаний')
    w.route_reminder.setMinimumHeight(76)
    w.route_reminder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    w.route_reminder.setObjectName('reminderLink')
    w.route_reminder.clicked.connect(lambda: open_reminder(w))
    foot = QHBoxLayout()
    for title, widget in (('Заметки по рейсу', w.route_note), ('Ближайшее напоминание', w.route_reminder)):
        card = QFrame()
        card.setObjectName('metricTile')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        label = QLabel(title)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        card.setFixedHeight(132)
        foot.addWidget(card, 1)
    box.addLayout(foot)
    details.setParent(None)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setMinimumWidth(450)
    scroll.setWidget(details)
    splitter.addWidget(scroll)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([700, 700])
    splitter.setHandleWidth(10)
    w.routes_splitter = splitter
    w._trips_compact_detail = False
    splitter.splitterMoved.connect(lambda *_: update_route_columns(w))


def adapt_trips(w):
    trips = w.navigation.currentRow() in (1, 4, 5)
    compact = trips and w.width() < 1200
    w.sidebar.setFixedWidth(76 if compact else 224 if trips else 254)
    w.sidebar.layout().setContentsMargins(10 if compact else 17, 20, 10 if compact else 17, 16)
    w.navigation.setStyleSheet('QListWidget::item { padding: 6px; margin: 2px 0; }' if trips else '')
    for label in w.sidebar_labels:
        label.setVisible(not compact)
    if trips:
        w.sidebar_labels[2].hide()
    for i, text in enumerate(('Сегодня', 'Рейсы', 'Машины', 'Карточка рейса', 'Архив', 'Корзина')):
        item = w.navigation.item(i)
        item.setText('' if compact else text)
        item.setToolTip(text)
    columns = 4 if w.width() < 1500 else 7
    for i, (button, _) in enumerate(w.summary_buttons.values()):
        w.summary_layout.addWidget(button, i // columns, i % columns)
    for icon in w.summary_icons:
        icon.setVisible(w.width() >= 1450)
    w.route_edit_button.setText('Редактировать\nрейс' if w.width() < 1200 else 'Редактировать рейс')
    w.route_reopen_button.setText('Вернуть в\nвыложенные' if w.width() < 1200 else 'Вернуть в выложенные')
    for button in (w.route_edit_button, w.route_reopen_button):
        button.setStyleSheet('min-height: 40px;' if w.width() < 1200 else '')
    w.route_open_button.setVisible(compact and not w._trips_compact_detail)
    w.route_open_button.setEnabled(w.selected_route_id() is not None)
    w.route_back_button.setVisible(compact and w._trips_compact_detail)
    if compact and w._trips_compact_detail and w.selected_route_id():
        w.routes_splitter.widget(0).hide()
        w.routes_splitter.widget(1).show()
    elif compact:
        w.routes_splitter.widget(1).hide()
        w.routes_splitter.widget(0).show()
    else:
        w.routes_splitter.widget(0).show()
        w.routes_splitter.widget(1).show()
    update_route_columns(w)
    # Parent resize events may precede the final splitter/viewport geometry.
    QTimer.singleShot(0, lambda: update_route_columns(w))


def update_route_columns(w):
    """Prioritize route, weight and status; never require horizontal scrolling."""
    if not hasattr(w, 'routes_table'):
        return
    viewport = w.routes_table.width()
    compact = w.navigation.currentRow() in (1, 4, 5) and w.width() < 1200
    w.routes_table.setColumnHidden(2, compact or viewport < 850)
    w.routes_table.setColumnHidden(4, compact or viewport < 690)
    w.routes_table.horizontalScrollBar().setValue(0)
    w.routes_table.resizeRowsToContents()


def open_route_compact(w):
    if w.navigation.currentRow() not in (1, 4, 5) or w.width() >= 1200:
        return
    if w.selected_route_id() is None:
        return
    w._trips_compact_detail = True
    adapt_trips(w)


def back_to_routes(w):
    w._trips_compact_detail = False
    adapt_trips(w)


def select_filter(w, key):
    w.route_filter = key
    w.show_closed.blockSignals(True)
    w.show_closed.setChecked(True)
    w.show_closed.blockSignals(False)
    w.refresh_routes()


def route_categories(route, agreed_ids, road_ids):
    if route['archived']:
        return {'archive'}
    result = {'all'}
    if route['status'] == 'Выложен' and route['id'] not in agreed_ids:
        result.add('search')
    if route['id'] in agreed_ids:
        result.add('agreed')
    if route.get('carrier_docs_pending'):
        result.add('docs')
    if route['id'] in road_ids:
        result.add('road')
    if route['status'] == 'Закрыт':
        result.add('closed')
    return result


def refresh_summary(w):
    agreed = {c['route_id'] for c in w.db.carriers() if c.get('status') == 'Согласован'}
    road = {r[0] for r in w.db.con.execute("SELECT route_id FROM route_tracking WHERE phase='В пути'")}
    categories = {r['id']: route_categories(r, agreed, road) for r in w.db.routes(include_archived=True)}
    for key, (button, caption) in w.summary_buttons.items():
        count = sum(key in values for values in categories.values())
        w.summary_values[key].setText(str(count))
        button.setChecked(w.route_filter == key and not w.deleted_only and not w.archive_only)
        button.setEnabled(not w.deleted_only and not w.archive_only)
    return categories


def update_trip_footer(w, route):
    w.route_note.setPlainText(route.get('note') or '' if route else '')
    pending = [r for r in w.db.reminder_rows() if route and r['route_id'] == route['id']]
    w.selected_reminder_id = pending[0]['id'] if pending else None
    if pending:
        title = reminder_title(pending[0]['kind'])
        # QLabel wraps naturally inside the clickable reminder card.
        text = title + '\n' + display_datetime(pending[0]['due_at'])
    else:
        text = 'Нет активных напоминаний'
    if not hasattr(w, 'reminder_text'):
        layout = QVBoxLayout(w.route_reminder)
        w.reminder_text = QLabel()
        w.reminder_text.setWordWrap(True)
        w.reminder_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(w.reminder_text)
        w.route_reminder.setText('')
    w.reminder_text.setText(text)
    w.route_reminder.setToolTip('Открыть контроль перевозки: ' + text)
    w.route_reminder.setEnabled(bool(pending))
    if not route:
        w.route_tabs.setTabText(0, 'Перевозчики')
        w.route_document_label.hide()


def open_reminder(w):
    reminder_id = w.selected_reminder_id
    w.navigation.setCurrentRow(0)
    w.refresh_today()
    for table in (w.today_table, w.upcoming_table):
        for row in range(table.rowCount()):
            if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == reminder_id:
                table.selectRow(row)
                table.scrollToItem(table.item(row, 0))
                return
    # The existing Today page normally shows only the next seven days.
    # Include a directly opened later task so its normal actions stay available.
    task = next((r for r in w.db.reminder_rows() if r['id'] == reminder_id), None)
    if task:
        ids = {w.upcoming_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
               for row in range(w.upcoming_table.rowCount())}
        tasks = [r for r in w.db.reminder_rows() if r['id'] in ids or r['id'] == reminder_id]
        w._fill_task_table(w.upcoming_table, tasks, show_state=False, selected_id=reminder_id)
        w.upcoming_label.setText('Ближайшие 7 дней и выбранное напоминание')
        w.on_upcoming_selection()
