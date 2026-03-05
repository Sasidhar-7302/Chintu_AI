import 'package:flutter/material.dart';

import '../models/a2ui.dart';

typedef A2UIActionCallback = Future<void> Function(
  String viewId,
  String actionId,
  Map<String, dynamic> payload,
  Map<String, dynamic> formData,
);

class A2UIOverlay extends StatelessWidget {
  final List<A2UIView> views;
  final A2UIActionCallback onAction;

  const A2UIOverlay({
    super.key,
    required this.views,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    if (views.isEmpty) return const SizedBox.shrink();

    final sorted = List<A2UIView>.from(views)
      ..sort((a, b) {
        final priorityCmp = b.priority.compareTo(a.priority);
        if (priorityCmp != 0) return priorityCmp;
        final aTime = a.createdAt?.millisecondsSinceEpoch ?? 0;
        final bTime = b.createdAt?.millisecondsSinceEpoch ?? 0;
        return bTime.compareTo(aTime);
      });

    final topView = sorted.first;

    return Positioned.fill(
      child: Stack(
        children: [
          ModalBarrier(
            dismissible: false,
            color: Colors.black.withValues(alpha: 0.45),
          ),
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 860, maxHeight: 700),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: _A2UIViewCard(
                  view: topView,
                  onAction: onAction,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _A2UIViewCard extends StatefulWidget {
  final A2UIView view;
  final A2UIActionCallback onAction;

  const _A2UIViewCard({required this.view, required this.onAction});

  @override
  State<_A2UIViewCard> createState() => _A2UIViewCardState();
}

class _A2UIViewCardState extends State<_A2UIViewCard> {
  final Map<String, _A2UIFormHandle> _forms = {};
  bool _submitting = false;

  void _registerForm(String formId, _A2UIFormHandle handle) {
    _forms[formId] = handle;
  }

  void _unregisterForm(String formId) {
    _forms.remove(formId);
  }

  Future<void> _handleAction(A2UIAction action) async {
    if (_submitting) return;

    if (action.requiresConfirmation) {
      final confirmed = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Confirm Action'),
              content: Text(
                action.confirmationMessage.isNotEmpty
                    ? action.confirmationMessage
                    : 'Are you sure you want to continue?',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Continue'),
                ),
              ],
            ),
          ) ??
          false;
      if (!confirmed) return;
    }

    final formId = action.formId;
    final formData =
        formId.isNotEmpty ? (_forms[formId]?.getValues() ?? <String, dynamic>{}) : <String, dynamic>{};

    setState(() => _submitting = true);
    try {
      await widget.onAction(widget.view.id, action.id, const {}, formData);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final view = widget.view;

    return Material(
      elevation: 12,
      borderRadius: BorderRadius.circular(20),
      color: theme.colorScheme.surface,
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: theme.colorScheme.outline.withValues(alpha: 0.15)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _Header(view: view),
            if (view.description.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(view.description, style: theme.textTheme.bodyMedium),
            ],
            const SizedBox(height: 14),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final component in view.components)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: _A2UIComponentRenderer(
                          component: component,
                          onRegisterForm: _registerForm,
                          onUnregisterForm: _unregisterForm,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                const Spacer(),
                for (final action in view.actions) ...[
                  _ActionButton(
                    action: action,
                    loading: _submitting,
                    onPressed: () => _handleAction(action),
                  ),
                  const SizedBox(width: 10),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  final A2UIView view;

  const _Header({required this.view});

  Color _severityColor(ColorScheme scheme) {
    switch (view.severity) {
      case 'success':
        return scheme.tertiary;
      case 'warning':
        return scheme.secondary;
      case 'error':
        return scheme.error;
      default:
        return scheme.primary;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = _severityColor(theme.colorScheme);
    return Row(
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(view.title, style: theme.textTheme.titleLarge),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Text(
            view.kind.toUpperCase(),
            style: theme.textTheme.labelMedium?.copyWith(color: color, fontWeight: FontWeight.w700),
          ),
        ),
      ],
    );
  }
}

class _ActionButton extends StatelessWidget {
  final A2UIAction action;
  final bool loading;
  final VoidCallback onPressed;

  const _ActionButton({
    required this.action,
    required this.loading,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final style = action.style;
    final isDanger = style == 'danger';
    final isPrimary = style == 'primary';

    final child = loading
        ? const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        : Text(action.label);

    if (isDanger) {
      return FilledButton.tonal(
        onPressed: loading ? null : onPressed,
        style: FilledButton.styleFrom(
          foregroundColor: Theme.of(context).colorScheme.error,
        ),
        child: child,
      );
    }

    if (isPrimary) {
      return FilledButton(
        onPressed: loading ? null : onPressed,
        child: child,
      );
    }

    return OutlinedButton(
      onPressed: loading ? null : onPressed,
      child: child,
    );
  }
}

typedef _FormRegister = void Function(String formId, _A2UIFormHandle handle);
typedef _FormUnregister = void Function(String formId);

class _A2UIComponentRenderer extends StatelessWidget {
  final A2UIComponent component;
  final _FormRegister onRegisterForm;
  final _FormUnregister onUnregisterForm;

  const _A2UIComponentRenderer({
    required this.component,
    required this.onRegisterForm,
    required this.onUnregisterForm,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final type = component.type;

    if (type == 'text' || type == 'markdown') {
      final text = component.text.isNotEmpty ? component.text : (component.data['text']?.toString() ?? '');
      return Text(text, style: theme.textTheme.bodyMedium);
    }

    if (type == 'key_value') {
      final items = (component.data['items'] as List?) ?? const [];
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final item in items.whereType<Map>())
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 120,
                    child: Text(
                      (item['key'] ?? '').toString(),
                      style: theme.textTheme.labelLarge,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      (item['value'] ?? '').toString(),
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
        ],
      );
    }

    if (type == 'form') {
      final formId = component.id.isNotEmpty ? component.id : (component.data['id']?.toString() ?? 'form');
      return _A2UIFormRenderer(
        formId: formId,
        data: component.data,
        onRegisterForm: onRegisterForm,
        onUnregisterForm: onUnregisterForm,
      );
    }

    if (type == 'code_diff') {
      final content = component.data['content']?.toString() ?? component.text;
      final maxHeight = (component.data['max_height'] as num?)?.toDouble() ?? 420;
      return Container(
        width: double.infinity,
        constraints: BoxConstraints(maxHeight: maxHeight),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.35),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: theme.colorScheme.outline.withValues(alpha: 0.15)),
        ),
        child: SingleChildScrollView(
          child: SelectableText(
            content,
            style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'Consolas', height: 1.35),
          ),
        ),
      );
    }

    if (type == 'table') {
      final columns = (component.data['columns'] as List?)?.map((e) => e.toString()).toList() ?? const [];
      final rows = (component.data['rows'] as List?) ?? const [];
      return SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columns: [
            for (final col in columns)
              DataColumn(
                label: Text(
                  col,
                  style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
          ],
          rows: [
            for (final row in rows.whereType<List>())
              DataRow(
                cells: [
                  for (final cell in row)
                    DataCell(
                      Text(
                        cell?.toString() ?? '',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                ],
              ),
          ],
        ),
      );
    }

    return Text('Unsupported component: $type', style: theme.textTheme.bodySmall);
  }
}

abstract class _A2UIFormHandle {
  Map<String, dynamic> getValues();
}

class _A2UIFormRenderer extends StatefulWidget {
  final String formId;
  final Map<String, dynamic> data;
  final _FormRegister onRegisterForm;
  final _FormUnregister onUnregisterForm;

  const _A2UIFormRenderer({
    required this.formId,
    required this.data,
    required this.onRegisterForm,
    required this.onUnregisterForm,
  });

  @override
  State<_A2UIFormRenderer> createState() => _A2UIFormRendererState();
}

class _A2UIFormRendererState extends State<_A2UIFormRenderer> implements _A2UIFormHandle {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, dynamic> _values = {};

  List<A2UIFormField> get _fields {
    final fieldsJson = (widget.data['fields'] as List?) ?? const [];
    return fieldsJson
        .whereType<Map>()
        .map((f) => A2UIFormField.fromJson(Map<String, dynamic>.from(f)))
        .toList();
  }

  @override
  void initState() {
    super.initState();
    widget.onRegisterForm(widget.formId, this);
  }

  @override
  void dispose() {
    widget.onUnregisterForm(widget.formId);
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  TextEditingController _controllerFor(A2UIFormField field) {
    return _controllers.putIfAbsent(field.name, () {
      final initial = field.defaultValue?.toString() ?? '';
      _values[field.name] = initial;
      return TextEditingController(text: initial);
    });
  }

  @override
  Map<String, dynamic> getValues() {
    final output = <String, dynamic>{};
    for (final field in _fields) {
      final name = field.name;
      final value = _values[name];
      output[name] = value;
    }
    return output;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = widget.data['title']?.toString() ?? '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (title.isNotEmpty) ...[
          Text(title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
        ],
        for (final field in _fields) ...[
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _buildField(context, field),
          ),
        ],
      ],
    );
  }

  Widget _buildField(BuildContext context, A2UIFormField field) {
    final type = field.type;
    if (type == 'checkbox') {
      final current = (_values[field.name] as bool?) ?? (field.defaultValue as bool?) ?? false;
      return CheckboxListTile(
        value: current,
        title: Text(field.label),
        onChanged: (value) => setState(() => _values[field.name] = value ?? false),
        contentPadding: EdgeInsets.zero,
      );
    }

    if (type == 'select') {
      final options = field.options;
      final currentValue = (_values[field.name]?.toString().isNotEmpty ?? false)
          ? _values[field.name].toString()
          : (options.isNotEmpty ? options.first.value : '');
      _values[field.name] = currentValue;
      return DropdownButtonFormField<String>(
        key: ValueKey('a2ui-${widget.formId}-${field.name}-$currentValue'),
        initialValue: currentValue.isNotEmpty ? currentValue : null,
        decoration: InputDecoration(
          labelText: field.label,
          hintText: field.placeholder,
        ),
        items: options
            .map((o) => DropdownMenuItem<String>(value: o.value, child: Text(o.label)))
            .toList(),
        onChanged: (value) => setState(() => _values[field.name] = value ?? ''),
      );
    }

    final controller = _controllerFor(field);
    final isMultiline = type == 'textarea' || type == 'multiline';
    final isPassword = type == 'password' || field.sensitive;
    final isNumber = type == 'number' || type == 'int' || type == 'float';

    return TextField(
      controller: controller,
      obscureText: isPassword,
      keyboardType: isNumber ? TextInputType.number : TextInputType.text,
      minLines: isMultiline ? 3 : 1,
      maxLines: isMultiline ? 6 : 1,
      onChanged: (value) => _values[field.name] = value,
      decoration: InputDecoration(
        labelText: field.label,
        hintText: field.placeholder,
      ),
    );
  }
}
