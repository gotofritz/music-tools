import yaml

# Recipe data extracted from the text
recipe_data = {
    "title": "Roast swede and purple sprouting broccoli curry",
    "source": "Meera Sodha",
    "cuisine": "Vegetables",
    "description": "A hearty and flavorful curry made with roasted swede and purple sprouting broccoli, using coconut milk and aromatic spices.",
    "tags": ["vegan", "curry", "roasted vegetables", "vegetarian", "gluten-free"],
    "directions": {
        "step": [
            "Heat the oven to 220C (200C fan)/425F/gas 7. Toss the swede wedges with three tablespoons of oil and three-quarters of a teaspoon of salt, then spread out on an oven tray and roast for 35-45 minutes, turning once halfway, until soft, tender and golden at the edges. Remove, and leave the oven on.",
            "While the swede is roasting, put four tablespoons of oil in a wide, ovenproof frying pan on a medium heat and, when hot, add the onion and one and a quarter teaspoons of salt. Cook, stirring, until the onion is soft and turning golden brown, then stir in the garlic and ginger and cook for another two minutes. Add the kashmiri chilli and turmeric, then tip in the tinned tomatoes and coconut milk, cook for 10 minutes more, and take off the heat.",
            "Add the broccoli and roast swede to the curry sauce, stir to coat, then pop the pan in the oven for 15 minutes, until the broccoli is tender and everything is well coated in the sauce.",
            "Finely slice the Thai basil leaves, fold half of them into the curry, then scatter the rest over the top. Serve warm with rice or flatbreads.",
        ]
    },
    "ingredients": {
        "serves": "4",
        "group": [
            {
                "name": "Main",
                "ingredient": [
                    {
                        "name": "swede",
                        "quantity": "2",
                        "measurement": "medium",
                        "preparation": "peeled, halved and cut into wedges of 2cm at their widest point",
                    },
                    {
                        "name": "onion",
                        "quantity": "1",
                        "measurement": "large",
                        "preparation": "peeled and finely sliced",
                    },
                    {
                        "name": "garlic",
                        "quantity": "6",
                        "measurement": "cloves",
                        "preparation": "peeled and minced",
                    },
                    {
                        "name": "ginger",
                        "quantity": "6",
                        "measurement": "cm x 2cm piece",
                        "preparation": "peeled and very finely chopped",
                    },
                    {
                        "name": "kashmiri chilli powder",
                        "quantity": "1½",
                        "measurement": "tsp",
                        "preparation": "",
                    },
                    {
                        "name": "ground turmeric",
                        "quantity": "1",
                        "measurement": "tsp",
                        "preparation": "",
                    },
                    {
                        "name": "tomatoes",
                        "quantity": "400",
                        "measurement": "g",
                        "preparation": "tin finely chopped, or rustic pomodoro",
                    },
                    {
                        "name": "coconut milk",
                        "quantity": "2",
                        "measurement": "tins",
                        "preparation": "",
                    },
                    {
                        "name": "sprouting broccoli",
                        "quantity": "400",
                        "measurement": "g",
                        "preparation": "florets kept whole, the rest cut into 2cm pieces",
                    },
                    {
                        "name": "Thai basil",
                        "quantity": "20",
                        "measurement": "g",
                        "preparation": "bunch, leaves picked",
                    },
                ],
            },
            {
                "name": "Garnish",
                "ingredient": [
                    {
                        "name": "Rice or flatbreads",
                        "quantity": null,
                        "measurement": null,
                        "preparation": "to serve",
                    }
                ],
            },
        ],
    },
}

# Convert to YAML
yaml_output = yaml.dump(recipe_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
print(yaml_output)
