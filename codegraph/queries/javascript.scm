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
  name: (identifier) @name.definition.class)

; Method definition
(method_definition
  name: (property_identifier) @name.definition.method)

; --- References ---

; import { X } from './module'
(import_statement
  source: (string) @name.reference.import)

; Class extends
(class_heritage
  (extends_clause
    value: (identifier) @name.reference.inherit))
