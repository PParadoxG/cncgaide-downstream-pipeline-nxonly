PREFIX nx: <https://cncgaide.org/ontology/nx/1.1#>
PREFIX cg: <https://cncgaide.org/ontology/nx/1.1/pipeline#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>

INSERT {
  GRAPH <{OUT}> {
    ?verdict a cg:Verdict ;
      cg:heuristic ?h ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome cg:NOT_EVALUABLE ;
      cg:gap [ cg:attribute ?attr ; cg:reason ?reason ] ;
      cg:scope "feature" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> {
    ?h a cg:Heuristic ; cg:scope "feature" ; cg:appliesTo ?cls ; cg:requires ?rq .
    ?rq cg:onClass ?cls ; cg:attribute ?attr .
  }
  GRAPH <{FACTS}> { ?f a ?cls ; cg:partOf ?part }
  FILTER NOT EXISTS { GRAPH <{FACTS}> { ?f ?attr ?any } }
  OPTIONAL { GRAPH <{FACTS}> { ?f cg:attributeGap ?g . ?g cg:attribute ?attr ; cg:reason ?r1 } }
  OPTIONAL { GRAPH <{FACTS}> { ?f cg:measurementRefusal ?m . ?m cg:quantity ?attr ; cg:reason ?r2 } }
  BIND(COALESCE(?r1, ?r2, "the feature carries no value for this attribute") AS ?reason)
  BIND(IRI(CONCAT(STR(?f), "/verdict/", STRAFTER(STR(?h), "#"))) AS ?verdict)
}
