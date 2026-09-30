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
      cg:heuristic cg:H15 ;
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_pocket_gap ; cg:value ?t_pocket_gap ] ;
      cg:value [ a cg:Value ; cg:name "pocketClearance" ; cg:value ?v_pocketClearance ] ;
      cg:scope "pair" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H15 cg:appliesTo ?clsA , ?clsB . cg:t_pocket_gap cg:value ?t_pocket_gap . }
  GRAPH <{FACTS}> {
    ?rel a cg:FeatureRelation ; cg:relationType cg:POCKET_CLEARANCE ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H15 cg:requires ?rq . ?rq cg:onClass ?clsA ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?a ?ra ?rv } }
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H15 cg:requires ?rq . ?rq cg:onClass ?clsB ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?b ?ra ?rv } }
  }
  GRAPH <{FACTS}> { ?rel cg:pocketClearance ?v_pocketClearance }
  BIND(IF(?v_pocketClearance >= ?t_pocket_gap, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?rel), "/verdict/H15")) AS ?verdict)
}
