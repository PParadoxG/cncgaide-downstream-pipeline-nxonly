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
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome cg:NOT_EVALUABLE ;
      cg:gap [ cg:onFeature ?x ; cg:attribute ?attr ; cg:reason ?reason ] ;
      cg:scope "pair" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> {
    ?h a cg:Heuristic ; cg:scope "pair" ; cg:relationType ?rt ; cg:appliesTo ?clsA , ?clsB .
  }
  GRAPH <{FACTS}> {
    ?rel a cg:FeatureRelation ; cg:relationType ?rt ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }
  { GRAPH <{FACTS}> { ?rel cg:from ?x . ?x a ?xcls } } UNION { GRAPH <{FACTS}> { ?rel cg:to ?x . ?x a ?xcls } }
  GRAPH <{ONTOLOGY}> { ?h cg:requires ?rq . ?rq cg:onClass ?xcls ; cg:attribute ?attr }
  FILTER NOT EXISTS { GRAPH <{FACTS}> { ?x ?attr ?any } }
  OPTIONAL { GRAPH <{FACTS}> { ?x cg:attributeGap ?g . ?g cg:attribute ?attr ; cg:reason ?r1 } }
  OPTIONAL { GRAPH <{FACTS}> { ?x cg:measurementRefusal ?m . ?m cg:quantity ?attr ; cg:reason ?r2 } }
  BIND(COALESCE(?r1, ?r2, "the feature carries no value for this attribute") AS ?reason)
  BIND(IRI(CONCAT(STR(?rel), "/verdict/", STRAFTER(STR(?h), "#"))) AS ?verdict)
}
