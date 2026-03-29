; --- Definitions ---

; Function declaration
(function_declaration
  name: (identifier) @name.definition.function)

; Method declaration
(method_declaration
  name: (field_identifier) @name.definition.method)

; Type declaration (struct, interface, etc.)
(type_declaration
  (type_spec
    name: (type_identifier) @name.definition.type))

; --- References ---

; import "package/name"
(import_spec
  path: (interpreted_string_literal) @name.reference.import)
