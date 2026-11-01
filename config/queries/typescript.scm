(function_declaration name: (identifier) @name) @definition.function
(generator_function_declaration name: (identifier) @name) @definition.function
(method_definition name: (property_identifier) @name) @definition.method
(class_declaration name: (type_identifier) @name) @definition.class
(abstract_class_declaration name: (type_identifier) @name) @definition.class
(interface_declaration name: (type_identifier) @name) @definition.interface
(type_alias_declaration name: (type_identifier) @name) @definition.type
(enum_declaration name: (identifier) @name) @definition.type
(variable_declarator name: (identifier) @name value: [(arrow_function) (function_expression)]) @definition.function
(variable_declarator name: (identifier) @name) @definition.var
[(identifier) (property_identifier) (type_identifier)] @reference
(comment) @comment
(import_statement source: (string (string_fragment) @import.path)) @import
(export_statement source: (string (string_fragment) @import.path)) @import
(call_expression function: (identifier) @_f arguments: (arguments . (string (string_fragment) @import.path)) (#eq? @_f "require")) @import
(call_expression function: (import) arguments: (arguments . (string (string_fragment) @import.path))) @import
