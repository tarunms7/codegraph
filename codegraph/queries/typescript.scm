; --- Definitions ---

; Function declaration
(function_declaration
  name: (identifier) @name.definition.function)

; Arrow function assigned to variable
(lexical_declaration
  (variable_declarator
    name: (identifier) @name.definition.function
    value: (arrow_function)))

; Class declaration
(class_declaration
  name: (type_identifier) @name.definition.class)

; Interface declaration
(interface_declaration
  name: (type_identifier) @name.definition.interface)

; Type alias
(type_alias_declaration
  name: (type_identifier) @name.definition.type)

; Method definition
(method_definition
  name: (property_identifier) @name.definition.method)

; Enum
(enum_declaration
  name: (identifier) @name.definition.enum)

; --- References ---

; import { X } from './module'
(import_statement
  source: (string) @name.reference.import)

; Class extends
(class_heritage
  (extends_clause
    value: (identifier) @name.reference.inherit))

; Class implements
(class_heritage
  (implements_clause
    (type_identifier) @name.reference.implement))
