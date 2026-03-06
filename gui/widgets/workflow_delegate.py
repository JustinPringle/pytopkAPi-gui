"""
gui/widgets/workflow_delegate.py
================================
WorkflowDelegate — custom QStyledItemDelegate for the left-dock workflow list.

Each row is painted as:
  [circle badge]  Step name
  - Grey ring  = not yet complete
  - Green fill = complete
  - Step number or checkmark inside the badge
"""

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle


_COMPLETE_BG  = QColor("#2ecc71")
_COMPLETE_FG  = QColor("#fff")
_PENDING_RING = QColor("#555")
_PENDING_FG   = QColor("#888")
_TEXT_FG      = QColor("#e8e8e8")
_TEXT_FG_SEL  = QColor("#fff")
_TEXT_FG_DONE = QColor("#a8e6bf")
_SEL_BG       = QColor("#1a6fc4")
_HOVER_BG     = QColor("#3e4245")
_DEFAULT_BG   = QColor("#313335")

_BADGE_SIZE = 22
_ROW_H      = 38
_BADGE_PAD  = 10


class WorkflowDelegate(QStyledItemDelegate):
    """Draws each workflow step with a numbered/checkmark badge."""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r        = option.rect
        step_num = index.row() + 1
        name     = index.data(Qt.ItemDataRole.DisplayRole) or ""
        done     = bool(index.data(Qt.ItemDataRole.UserRole))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ── Background ────────────────────────────────────────────────────────
        if selected:
            bg = _SEL_BG
        elif hovered:
            bg = _HOVER_BG
        else:
            bg = _DEFAULT_BG
        painter.fillRect(r, bg)

        # ── Badge ─────────────────────────────────────────────────────────────
        bx = r.x() + _BADGE_PAD
        by = r.y() + (r.height() - _BADGE_SIZE) // 2
        badge = QRect(bx, by, _BADGE_SIZE, _BADGE_SIZE)

        if done:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_COMPLETE_BG)
            painter.drawEllipse(badge)
            painter.setPen(_COMPLETE_FG)
            f = QFont(painter.font())
            f.setPointSize(9)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            pen = QPen(_PENDING_RING, 1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(badge)
            painter.setPen(_PENDING_FG)
            f = QFont(painter.font())
            f.setPointSize(8)
            f.setBold(False)
            painter.setFont(f)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(step_num))

        # ── Step name ─────────────────────────────────────────────────────────
        tx = bx + _BADGE_SIZE + 8
        text_rect = QRect(tx, r.y(), r.width() - tx + r.x() - 6, r.height())

        if selected:
            fg = _TEXT_FG_SEL
        elif done:
            fg = _TEXT_FG_DONE
        else:
            fg = _TEXT_FG

        painter.setPen(fg)
        f = QFont(painter.font())
        f.setPointSize(11)
        f.setBold(selected)
        painter.setFont(f)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name,
        )

        # Bottom separator (subtle)
        if not selected:
            painter.setPen(QPen(QColor("#3a3d40"), 1))
            painter.drawLine(r.left() + 4, r.bottom(), r.right() - 4, r.bottom())

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), _ROW_H)
