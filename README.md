# Available doctor appointments visualization
This is a software tool which does the following:
1. Crawls and fetches data about availability of doctors appointments in several Kupot Holim
2. Extracts the data based on geography and field of experties
3. Merges the data from the different Kupot Holim
4. Visualizes the data on a map

## How To Run
TODO

## The Codebase
The Codebase contains seperate crawlers for each Kupat Holim and the Visualization tool

The Clalit crawler is documented in [Clalit_README.md]

The Maccabi crawler is documented in [Maccabi_README.md] (TODO)

The Visualization tool is documented in [visualization_README.md] (TODO)

## FUTURE WORK
Currently, this tool is a POC on very real data, but not a fully working application.
Also, constant-paths are proabably broken...

Future work:

1. Add the other Kupot Holim (Meuhedet, Leumit)
2. Debug, Fine-tune and improve the crawling of Clalit and Maccabi
2.1. In Maccabi - the crawling didn't succeed to query for family doctors (since there were too much)
2.2. In clalit - since the querying was too slow - only several fields were queried.
2.3. Both of them need to be researched for duplicates, misfits between them and other data errors
2.3.1 For example - Tel-Aviv vs Tel-Aviv-Yafo vs Tel Aviv. א.א.ג vs אף אוזן גרון, נשים vs גניקולוגיה etc.
3. Add more statistics
3.1 Normalize per city-capita
3.2 Create a more complex metrics that match desireable behavior and does not encourage hiding data from clients. For example look at K-closest appointments rather than just one, and reward appointments that occur at a closer date.
3.3 Look at trends over time, and average over longer time prediods
4. Make the Crawling run periodically and update a database
5. Debug and improve the visualization
6. Tidy and document the code
