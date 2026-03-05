import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class LiveCanvasPanel extends StatefulWidget {
  final Map<String, dynamic> canvasState;
  final void Function(Map<String, dynamic>) onAction;

  const LiveCanvasPanel({
    super.key,
    required this.canvasState,
    required this.onAction,
  });

  @override
  State<LiveCanvasPanel> createState() => _LiveCanvasPanelState();
}

class _LiveCanvasPanelState extends State<LiveCanvasPanel> {
  String? _selectedBoardId;

  List<Map<String, dynamic>> _boardsFromState() {
    final boardsRaw = widget.canvasState['boards'];
    if (boardsRaw is! List) return [];
    return boardsRaw
        .whereType<Map>()
        .map((b) => Map<String, dynamic>.from(b))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final boards = _boardsFromState();
    if (boards.isEmpty) {
      return Center(
        child: Text(
          'Canvas is warming up...',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: AppColors.textMuted),
        ),
      );
    }

    final selectedBoard = _resolveSelectedBoard(boards);
    final columns = _sortedColumns(selectedBoard);
    final cards = _cardsForBoard(selectedBoard);
    final isLocked = (selectedBoard['meta'] as Map?)?['locked'] == true;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _BoardTabs(
          boards: boards,
          selectedId: selectedBoard['id'] as String? ?? '',
          onSelect: (id) => setState(() => _selectedBoardId = id),
        ),
        const SizedBox(height: 8),
        _BoardMetaRow(meta: (selectedBoard['meta'] as Map?)?.cast<String, dynamic>() ?? const {}),
        const SizedBox(height: 12),
        Expanded(
          child: Scrollbar(
            thumbVisibility: true,
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: columns.map((column) {
                  final columnId = column['id'] as String? ?? '';
                  final columnCards = _cardsForColumn(cards, columnId);
                  return _CanvasColumn(
                    boardId: selectedBoard['id'] as String? ?? '',
                    column: column,
                    cards: columnCards,
                    columnIds: columns.map((c) => c['id'] as String? ?? '').toList(),
                    isLocked: isLocked,
                    onAction: widget.onAction,
                  );
                }).toList(),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Map<String, dynamic> _resolveSelectedBoard(List<Map<String, dynamic>> boards) {
    if (_selectedBoardId != null) {
      for (final board in boards) {
        if (board['id'] == _selectedBoardId) {
          return board;
        }
      }
    }
    return boards.first;
  }

  List<Map<String, dynamic>> _sortedColumns(Map<String, dynamic> board) {
    final colsRaw = board['columns'];
    if (colsRaw is! List) return [];
    final cols = colsRaw.whereType<Map>().map((c) => Map<String, dynamic>.from(c)).toList();
    cols.sort((a, b) => ((a['order'] as num?) ?? 0).compareTo((b['order'] as num?) ?? 0));
    return cols;
  }

  List<Map<String, dynamic>> _cardsForBoard(Map<String, dynamic> board) {
    final cardsRaw = board['cards'];
    if (cardsRaw is! List) return [];
    final cards = cardsRaw.whereType<Map>().map((c) => Map<String, dynamic>.from(c)).toList();
    cards.sort((a, b) => ((a['priority'] as num?) ?? 0).compareTo((b['priority'] as num?) ?? 0));
    return cards;
  }

  List<Map<String, dynamic>> _cardsForColumn(List<Map<String, dynamic>> cards, String columnId) {
    return cards.where((card) => (card['status'] as String? ?? '') == columnId).toList();
  }
}

class _BoardTabs extends StatelessWidget {
  final List<Map<String, dynamic>> boards;
  final String selectedId;
  final ValueChanged<String> onSelect;

  const _BoardTabs({
    required this.boards,
    required this.selectedId,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: boards.map((board) {
          final id = board['id'] as String? ?? '';
          final title = board['title'] as String? ?? id;
          final isActive = id == selectedId;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: InkWell(
              onTap: () => onSelect(id),
              borderRadius: BorderRadius.circular(12),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color: isActive
                      ? AppColors.accent.withValues(alpha: 0.18)
                      : AppColors.surfaceStrong.withValues(alpha: 0.4),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isActive
                        ? AppColors.accent.withValues(alpha: 0.6)
                        : AppColors.border.withValues(alpha: 0.6),
                  ),
                ),
                child: Text(
                  title,
                  style: TextStyle(
                    color: isActive ? AppColors.accent : AppColors.textMuted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _BoardMetaRow extends StatelessWidget {
  final Map<String, dynamic> meta;

  const _BoardMetaRow({required this.meta});

  @override
  Widget build(BuildContext context) {
    if (meta.isEmpty) {
      return const SizedBox.shrink();
    }

    final items = <String>[];
    if (meta['goal'] != null) items.add('Goal: ${meta['goal']}');
    if (meta['risk'] != null) items.add('Risk: ${meta['risk']}');
    if (meta['eta_seconds'] != null) items.add('ETA: ${meta['eta_seconds']}s');
    if (items.isEmpty) {
      return const SizedBox.shrink();
    }

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: items.map((item) {
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.surfaceStrong.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
          ),
          child: Text(
            item,
            style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
          ),
        );
      }).toList(),
    );
  }
}

class _CanvasColumn extends StatelessWidget {
  final String boardId;
  final Map<String, dynamic> column;
  final List<Map<String, dynamic>> cards;
  final List<String> columnIds;
  final bool isLocked;
  final void Function(Map<String, dynamic>) onAction;

  const _CanvasColumn({
    required this.boardId,
    required this.column,
    required this.cards,
    required this.columnIds,
    required this.isLocked,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final columnId = column['id'] as String? ?? '';
    final title = column['title'] as String? ?? columnId;

    return Container(
      width: 260,
      margin: const EdgeInsets.only(right: 14),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              const Spacer(),
              if (!isLocked)
                IconButton(
                  icon: const Icon(Icons.add, size: 16, color: AppColors.accent),
                  onPressed: () {
                    onAction({
                      'board_id': boardId,
                      'action': 'add_card',
                      'status': columnId,
                      'title': 'New card',
                    });
                  },
                ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: cards.isEmpty
                ? Center(
                    child: Text(
                      'No cards',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.textMuted),
                    ),
                  )
                : ListView.builder(
                    itemCount: cards.length,
                    itemBuilder: (context, index) => _CanvasCardTile(
                      boardId: boardId,
                      columnId: columnId,
                      card: cards[index],
                      columnIds: columnIds,
                      isLocked: isLocked,
                      onAction: onAction,
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _CanvasCardTile extends StatelessWidget {
  final String boardId;
  final String columnId;
  final Map<String, dynamic> card;
  final List<String> columnIds;
  final bool isLocked;
  final void Function(Map<String, dynamic>) onAction;

  const _CanvasCardTile({
    required this.boardId,
    required this.columnId,
    required this.card,
    required this.columnIds,
    required this.isLocked,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final title = card['title'] as String? ?? 'Untitled';
    final body = card['body'] as String? ?? '';
    final tags = (card['tags'] as List?)?.map((t) => t.toString()).toList() ?? const [];
    final cardId = card['id'] as String? ?? '';
    final currentIndex = columnIds.indexOf(columnId);
    final canMoveLeft = !isLocked && currentIndex > 0;
    final canMoveRight = !isLocked && currentIndex < columnIds.length - 1;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
          if (body.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              body,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11, height: 1.3),
            ),
          ],
          if (tags.isNotEmpty) ...[
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: tags.map((tag) {
                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: AppColors.surfaceStrong.withValues(alpha: 0.5),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
                  ),
                  child: Text(tag, style: const TextStyle(fontSize: 10, color: AppColors.textMuted)),
                );
              }).toList(),
            ),
          ],
          const SizedBox(height: 6),
          Row(
            children: [
              if (canMoveLeft)
                IconButton(
                  icon: const Icon(Icons.chevron_left, size: 18, color: AppColors.accent),
                  onPressed: () => onAction({
                    'board_id': boardId,
                    'action': 'move_card',
                    'card_id': cardId,
                    'target_column': columnIds[currentIndex - 1],
                  }),
                ),
              if (canMoveRight)
                IconButton(
                  icon: const Icon(Icons.chevron_right, size: 18, color: AppColors.accent),
                  onPressed: () => onAction({
                    'board_id': boardId,
                    'action': 'move_card',
                    'card_id': cardId,
                    'target_column': columnIds[currentIndex + 1],
                  }),
                ),
              const Spacer(),
              if (!isLocked)
                IconButton(
                  icon: const Icon(Icons.delete_outline, size: 16, color: AppColors.danger),
                  onPressed: () => onAction({
                    'board_id': boardId,
                    'action': 'remove_card',
                    'card_id': cardId,
                  }),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
