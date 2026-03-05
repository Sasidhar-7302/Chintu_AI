import 'dart:convert';

class A2UIView {
  final String schemaVersion;
  final String id;
  final String kind;
  final String title;
  final String description;
  final int priority;
  final String severity;
  final List<A2UIComponent> components;
  final List<A2UIAction> actions;
  final Map<String, dynamic> meta;
  final DateTime? createdAt;

  const A2UIView({
    required this.schemaVersion,
    required this.id,
    required this.kind,
    required this.title,
    required this.description,
    required this.priority,
    required this.severity,
    required this.components,
    required this.actions,
    required this.meta,
    required this.createdAt,
  });

  factory A2UIView.fromJson(Map<String, dynamic> json) {
    final componentsJson = (json['components'] as List?) ?? const [];
    final actionsJson = (json['actions'] as List?) ?? const [];
    final createdAtRaw = json['created_at'] as String?;

    return A2UIView(
      schemaVersion: json['schema_version'] as String? ?? 'a2ui-1.0',
      id: json['id'] as String? ?? '',
      kind: json['kind'] as String? ?? 'view',
      title: json['title'] as String? ?? 'Untitled',
      description: json['description'] as String? ?? '',
      priority: (json['priority'] as num?)?.toInt() ?? 5,
      severity: json['severity'] as String? ?? 'info',
      components: componentsJson
          .whereType<Map>()
          .map((c) => A2UIComponent.fromJson(Map<String, dynamic>.from(c)))
          .toList(),
      actions: actionsJson
          .whereType<Map>()
          .map((a) => A2UIAction.fromJson(Map<String, dynamic>.from(a)))
          .toList(),
      meta: (json['meta'] as Map?)?.cast<String, dynamic>() ?? const {},
      createdAt: createdAtRaw != null ? DateTime.tryParse(createdAtRaw) : null,
    );
  }
}

class A2UIComponent {
  final String type;
  final String id;
  final String text;
  final Map<String, dynamic> data;

  const A2UIComponent({
    required this.type,
    required this.id,
    required this.text,
    required this.data,
  });

  factory A2UIComponent.fromJson(Map<String, dynamic> json) {
    return A2UIComponent(
      type: json['type'] as String? ?? 'text',
      id: json['id'] as String? ?? '',
      text: json['text'] as String? ?? '',
      data: (json['data'] as Map?)?.cast<String, dynamic>() ?? const {},
    );
  }
}

class A2UIAction {
  final String id;
  final String label;
  final String style;
  final String actionType;
  final String formId;
  final bool requiresConfirmation;
  final String confirmationMessage;

  const A2UIAction({
    required this.id,
    required this.label,
    required this.style,
    required this.actionType,
    required this.formId,
    required this.requiresConfirmation,
    required this.confirmationMessage,
  });

  factory A2UIAction.fromJson(Map<String, dynamic> json) {
    return A2UIAction(
      id: json['id'] as String? ?? '',
      label: json['label'] as String? ?? 'Action',
      style: json['style'] as String? ?? 'secondary',
      actionType: json['action_type'] as String? ?? 'action',
      formId: json['form_id'] as String? ?? '',
      requiresConfirmation: json['requires_confirmation'] as bool? ?? false,
      confirmationMessage: json['confirmation_message'] as String? ?? '',
    );
  }
}

class A2UIFormField {
  final String name;
  final String label;
  final String type;
  final bool requiredField;
  final String placeholder;
  final List<A2UIOption> options;
  final dynamic defaultValue;
  final bool sensitive;

  const A2UIFormField({
    required this.name,
    required this.label,
    required this.type,
    required this.requiredField,
    required this.placeholder,
    required this.options,
    required this.defaultValue,
    required this.sensitive,
  });

  factory A2UIFormField.fromJson(Map<String, dynamic> json) {
    final optionsJson = (json['options'] as List?) ?? const [];
    return A2UIFormField(
      name: json['name'] as String? ?? '',
      label: json['label'] as String? ?? (json['name'] as String? ?? ''),
      type: json['type'] as String? ?? 'text',
      requiredField: json['required'] as bool? ?? false,
      placeholder: json['placeholder'] as String? ?? '',
      options: optionsJson
          .whereType<Map>()
          .map((o) => A2UIOption.fromJson(Map<String, dynamic>.from(o)))
          .toList(),
      defaultValue: json['default'],
      sensitive: json['sensitive'] as bool? ?? false,
    );
  }
}

class A2UIOption {
  final String label;
  final String value;

  const A2UIOption({required this.label, required this.value});

  factory A2UIOption.fromJson(Map<String, dynamic> json) {
    final value = json['value']?.toString() ?? '';
    return A2UIOption(
      label: json['label']?.toString() ?? value,
      value: value,
    );
  }
}

String encodeA2UIActionPayload({
  required String viewId,
  required String actionId,
  Map<String, dynamic>? payload,
  Map<String, dynamic>? form,
}) {
  return jsonEncode({
    'type': 'a2ui_action',
    'data': {
      'view_id': viewId,
      'action_id': actionId,
      if (payload != null) 'payload': payload,
      if (form != null) 'form': form,
    }
  });
}

