from typing import Dict

CYPHER_TEMPLATES: Dict[str, str] = {
    "FIND_SUBSIDIARIES": """
        MATCH (company:Entity)-[:OWNS|HAS_SUBSIDIARY]->(sub:Entity)
        WHERE toLower(company.name) CONTAINS toLower($entity_name)
        RETURN company.name AS Parent, sub.name AS Subsidiary, labels(sub) AS Type
        LIMIT 50
    """,
    
    "FIND_PARENT_COMPANY": """
        MATCH (parent:Entity)-[:OWNS|HAS_SUBSIDIARY]->(company:Entity)
        WHERE toLower(company.name) CONTAINS toLower($entity_name)
        RETURN company.name AS Subsidiary, parent.name AS Parent, labels(parent) AS Type
        LIMIT 50
    """,
    
    "FIND_KEY_PERSONNEL": """
        MATCH (person:Entity)-[:DIRECTOR_OF|CEO_OF|CFO_OF|WORKS_FOR|KEY_MANAGERIAL_PERSONNEL]->(company:Entity)
        WHERE toLower(company.name) CONTAINS toLower($entity_name)
        RETURN person.name AS Person, company.name AS Company, labels(person) AS Role
        LIMIT 50
    """,
    
    "FIND_AUDITORS": """
        MATCH (auditor:Entity)-[:AUDITS|STATUTORY_AUDITOR]->(company:Entity)
        WHERE toLower(company.name) CONTAINS toLower($entity_name)
        RETURN auditor.name AS Auditor, company.name AS Company
        LIMIT 50
    """,
    
    "GENERAL_RELATIONSHIPS": """
        MATCH (e1:Entity)-[r]-(e2:Entity)
        WHERE toLower(e1.name) CONTAINS toLower($entity_name)
        RETURN e1.name AS Source, type(r) AS Relationship, e2.name AS Target
        LIMIT 50
    """
}
