(class_declaration name: (identifier) @name) @definition.class
(interface_declaration name: (identifier) @name) @definition.interface
(enum_declaration name: (identifier) @name) @definition.type
(record_declaration name: (identifier) @name) @definition.class
(method_declaration name: (identifier) @name) @definition.method
(constructor_declaration name: (identifier) @name) @definition.method
[(identifier) (type_identifier)] @reference
[(line_comment) (block_comment)] @comment
(import_declaration [(scoped_identifier) (identifier)] @import.path) @import
