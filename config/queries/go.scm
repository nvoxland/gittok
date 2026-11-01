(function_declaration name: (identifier) @name) @definition.function
(method_declaration name: (field_identifier) @name) @definition.method
(type_spec name: (type_identifier) @name) @definition.type
[(identifier) (field_identifier) (type_identifier)] @reference
(comment) @comment
(import_spec path: (interpreted_string_literal (interpreted_string_literal_content) @import.path)) @import
