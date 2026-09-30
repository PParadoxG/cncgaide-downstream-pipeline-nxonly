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
      cg:heuristic cg:H18 ;
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_hole_near ; cg:value ?t_hole_near ] ;
      cg:usedThreshold [ cg:threshold cg:tol_diameter ; cg:value ?tol_diameter ] ;
      cg:value [ a cg:Value ; cg:name "axisSpacing" ; cg:value ?v_axisSpacing ] ;
      cg:value [ a cg:Value ; cg:name "baseDiameterA" ; cg:value ?v_baseDiameterA ] ;
      cg:value [ a cg:Value ; cg:name "baseDiameterB" ; cg:value ?v_baseDiameterB ] ;
      cg:value [ a cg:Value ; cg:name "nearGate" ; cg:value ?v_nearGate ] ;
      cg:value [ a cg:Value ; cg:name "diameterDifference" ; cg:value ?v_diameterDifference ] ;
      cg:scope "pair" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H18 cg:appliesTo ?clsA , ?clsB . cg:t_hole_near cg:value ?t_hole_near . cg:tol_diameter cg:value ?tol_diameter . }
  GRAPH <{FACTS}> {
    ?rel a cg:FeatureRelation ; cg:relationType cg:HOLE_SPACING ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H18 cg:requires ?rq . ?rq cg:onClass ?clsA ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?a ?ra ?rv } }
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H18 cg:requires ?rq . ?rq cg:onClass ?clsB ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?b ?ra ?rv } }
  }
  GRAPH <{ONTOLOGY}> { ?clsA cg:baseDiameterAttribute ?dpA . ?clsB cg:baseDiameterAttribute ?dpB }
  GRAPH <{FACTS}> { ?rel cg:axisSpacing ?v_axisSpacing . ?a ?dpA ?v_baseDiameterA . ?b ?dpB ?v_baseDiameterB }
  BIND(?t_hole_near * IF(?v_baseDiameterA > ?v_baseDiameterB, ?v_baseDiameterA, ?v_baseDiameterB) AS ?v_nearGate)
  FILTER(?v_axisSpacing <= ?v_nearGate)
  BIND(ABS(?v_baseDiameterA - ?v_baseDiameterB) AS ?v_diameterDifference)
  BIND(IF(?v_diameterDifference <= ?tol_diameter, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?rel), "/verdict/H18")) AS ?verdict)
}
