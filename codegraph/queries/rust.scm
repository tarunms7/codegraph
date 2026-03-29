; --- Definitions ---

; Function definition
(function_item
  name: (identifier) @name.definition.function)

; Struct definition
(struct_item
  name: (type_identifier) @name.definition.class)

; Enum definition
(enum_item
  name: (type_identifier) @name.definition.enum)

; Trait definition
(trait_item
  name: (type_identifier) @name.definition.interface)

; Type alias
(type_item
  name: (type_identifier) @name.definition.type)

; Method inside impl block
(impl_item
  body: (declaration_list
    (function_item
      name: (identifier) @name.definition.method)))

; --- References ---

; use some::path
(use_declaration
  argument: (scoped_identifier) @name.reference.import)

; use single_ident
(use_declaration
  argument: (identifier) @name.reference.import)
