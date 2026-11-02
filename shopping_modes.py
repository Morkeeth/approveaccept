"""Bounded use suggestions, separate from merchant facts and the purchased product.

AI chooses fit/order and cites an allowed action. These authored ideas never claim
that a merchant sells an event, booking, personalisation service or extra supplies.
"""
import copy

MODE_CONTEXT = {
 'surprise': {'title':'A small surprise, picked for you','intent':'Choose a small unexpected delight that fits the stated tastes; favour a playful new use over a routine gift.','action_label':'Try something small'},
 'gift': {'title':'A gift with a personal touch','intent':'Choose a thoughtful gift matching the stated recipient tastes; include a simple personal gesture the buyer can do.','action_label':'Make it personal'},
 'date': {'title':'An at-home date idea','intent':'Choose a shared at-home activity for two using one of these products. No venue, event, restaurant or booking is connected.','action_label':'Do it together'},
}

# Handle and product type both have to match the current first-party record.
ACTIONS = {
 'carnet-merci-maison-beige': ('Carnet', {
  'surprise': ('surprise-notebook','Make a tiny adventure list', ['Write down three small things you have never tried.','Pick one to do this week. A pen you already own is needed.']),
  'gift': ('gift-notebook','Give their next idea a home', ['Write a personal note on the first page before giving it.','Leave the rest for their ideas. A pen you already own is needed.']),
  'date': ('date-notebook','Trade three questions', ['Each write three questions in the notebook.','Take turns answering and choose one small plan together. Use a pen you already own.']),
 }),
 'trousse-en-lin-lave-carreaux-bibliotheque': ('Trousse', {
  'surprise': ('surprise-pouch','Give a small collection a home', ['Choose a few little things you already enjoy.','Keep them together in the linen pouch; extra contents are not included.']),
  'gift': ('gift-pouch','A little place for their favourites', ['Give the linen pouch with a personal note.','Optional contents and a note are your own additions, not included by the merchant.']),
 }),
 'jeu-scoubidous': ('Jeux', {
  'surprise': ('surprise-craft','Make something with your hands', ['Try the scoubidou craft using the product instructions.','Keep your first attempt, even if it is uneven.']),
  'gift': ('gift-craft','Give a playful making break', ['Give the scoubidou craft as a small hands-on gift.','Add a note inviting them to show you what they make; the note is your own addition.']),
  'date': ('date-craft','Make a keepsake together', ['Try the scoubidou craft together using the included instructions.','Take turns and decide together what to make. This is an at-home suggestion, not a workshop booking.']),
 }),
}


def prepare(items, mode):
 if mode not in MODE_CONTEXT:
  raise ValueError('Unknown shopping mode.')
 out=[]
 for original in items:
  spec=ACTIONS.get(original['quote'].get('handle'))
  if not spec or original.get('product_type') != spec[0] or mode not in spec[1]:
   continue
  action_id,title,steps=spec[1][mode];item=copy.deepcopy(original)
  item['action']={'id':action_id,'mode':mode,'title':title,'steps':steps,
                  'label':MODE_CONTEXT[mode]['action_label'],
                  'scope':'At-home activity suggestion; product only, no booking.' if mode=='date' else
                          'Use suggestion; product only, personal additions are not included.'}
  out.append(item)
 if not out:
  raise ValueError('No current products support this mode. No purchase was made.')
 return out
