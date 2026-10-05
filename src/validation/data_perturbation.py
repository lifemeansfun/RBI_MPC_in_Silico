"""
Data Perturbation and Entity Masking Protocols (Mitigation for Data Leakage).
Implements the "Entity-Masked Perturbation" protocol to verify if the LLM is reasoning or memorizing.
"""

import copy
import re
from src.schemas.macro_schema import MacroMeetingSnapshot

class DataPerturbator:
    """
    Handles systematic shocking of macroeconomic data and masking of identifying entities.
    """

    ENTITY_MAP = {
        "Reserve Bank of India": "Central Bank of Country X",
        "RBI": "Central Bank",
        "India": "Country X",
        "Shaktikanta Das": "Chairperson A",
        "Michael Patra": "Internal Member B",
        "Rajiv Ranjan": "Internal Member C",
        "Shashanka Bhide": "External Member D",
        "Ashima Goyal": "External Member E",
        "Jayanth Varma": "External Member F",
        "Jayanth R. Varma": "External Member F",
        "INR": "LCU (Local Currency Unit)",
        "Crore": "Billion",
        "Monsoon": "Seasonal Weather",
        "LPA": "Long Period Average",
    }

    @staticmethod
    def apply_macro_shock(snapshot: MacroMeetingSnapshot, 
                          cpi_shock: float = 0.0, 
                          food_shock: float = 0.0,
                          fed_shock: float = 0.0) -> MacroMeetingSnapshot:
        """
        Injects a structural macroeconomic shock into the snapshot to test reasoning vs memorization.
        """
        perturbed = snapshot.model_copy(deep=True)
        perturbed.cpi_headline_yoy_pct += cpi_shock
        
        if perturbed.cpi_core_yoy_pct is not None:
            # Assume core inflation absorbs a fraction of headline shock if it's broad based
            pass 
            
        if perturbed.cpi_food_yoy_pct is not None and food_shock != 0.0:
            perturbed.cpi_food_yoy_pct += food_shock
            
        if perturbed.us_fed_funds_rate_pct is not None and fed_shock != 0.0:
            perturbed.us_fed_funds_rate_pct += fed_shock
            
        return perturbed

    @staticmethod
    def mask_entities_in_text(text: str) -> str:
        """
        Replaces all known specific institutional identifiers with generic equivalents.
        """
        masked_text = text
        # Process longer strings first to avoid partial replacements
        sorted_keys = sorted(DataPerturbator.ENTITY_MAP.keys(), key=len, reverse=True)
        for key in sorted_keys:
            replacement = DataPerturbator.ENTITY_MAP[key]
            # Use regex with word boundaries where appropriate, but simple replace is often fine for names
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            masked_text = pattern.sub(replacement, masked_text)
            
        # Additional cleanup
        masked_text = masked_text.replace("Rs.", "LCU")
        masked_text = masked_text.replace("Rupee", "Local Currency")
        masked_text = masked_text.replace("Rupees", "Local Currency")
        
        return masked_text

    @staticmethod
    def get_masked_prompt(snapshot: MacroMeetingSnapshot) -> str:
        """
        Generates the standard prompt text from a snapshot, but masks all entities.
        """
        raw_prompt = snapshot.to_prompt_text()
        return DataPerturbator.mask_entities_in_text(raw_prompt)

