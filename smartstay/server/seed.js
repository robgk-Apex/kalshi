import { getDb, load, flush, id } from './store.js';
import { hashPassword } from './auth.js';

const img = (photoId, w = 1200) =>
  `https://images.unsplash.com/photo-${photoId}?auto=format&fit=crop&w=${w}&q=80`;

const AVATAR = (seed) => `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(seed)}`;

// Deterministic dates relative to "now" so seeded content always looks fresh.
const daysFromNow = (n) => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const isoAgo = (days) => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString();
};

export function seedIfEmpty(force = false) {
  const db = getDb();
  if (db.meta.seeded && !force) return;

  db.users = [];
  db.listings = [];
  db.bookings = [];
  db.reviews = [];
  db.favorites = [];
  db.messages = [];

  // ---- Hosts & guests ----
  const mk = (name, email, isHost) => {
    const u = {
      id: id(),
      name,
      email: email.toLowerCase(),
      passwordHash: hashPassword('password123'),
      isHost,
      avatar: AVATAR(name),
      bio: isHost ? `Superhost sharing beautiful spaces across the country.` : '',
      createdAt: isoAgo(400),
    };
    db.users.push(u);
    return u;
  };

  const sofia = mk('Sofia Reyes', 'sofia@smartstay.us', true);
  const marcus = mk('Marcus Bell', 'marcus@smartstay.us', true);
  const priya = mk('Priya Nair', 'priya@smartstay.us', true);
  const demo = mk('Demo Guest', 'guest@smartstay.us', false);
  const reviewers = [
    mk('James Carter', 'james@example.com', false),
    mk('Emily Zhang', 'emily@example.com', false),
    mk('Diego Alvarez', 'diego@example.com', false),
    mk('Hannah Lee', 'hannah@example.com', false),
    mk('Tom Okafor', 'tom@example.com', false),
  ];

  const L = [
    {
      host: sofia,
      title: 'Cliffside Malibu Villa with Infinity Pool',
      type: 'Villa',
      city: 'Malibu', state: 'CA', lat: 34.0259, lng: -118.7798,
      bedrooms: 4, beds: 5, bathrooms: 4, maxGuests: 8,
      desc: 'Wake up to the Pacific from every room. This architectural showcase perches above Zuma Beach with floor-to-ceiling glass, an infinity pool that melts into the horizon, and a chef’s kitchen built for long, slow mornings.',
      amenities: ['Wifi', 'Kitchen', 'Pool', 'Hot tub', 'Ocean view', 'Free parking', 'Air conditioning', 'EV charger', 'Workspace', 'BBQ grill', 'Patio'],
      photos: [img('1613490493576-7fde63acd811'), img('1600585154340-be6161a56a0c'), img('1600566753086-00f18fb6b3ea'), img('1600210492486-724fe5c67fb0'), img('1600607687939-ce8a6c25118c')],
      pricing: { nightly: 1450, weekendNightly: 1750, weeklyDiscountPct: 12, monthlyDiscountPct: 28, cleaningFee: 350 },
      minNights: 3, instantBook: true,
    },
    {
      host: marcus,
      title: 'Ski-in/Ski-out Aspen Mountain Lodge',
      type: 'Cabin',
      city: 'Aspen', state: 'CO', lat: 39.1911, lng: -106.8175,
      bedrooms: 5, beds: 7, bathrooms: 4, maxGuests: 10,
      desc: 'Timber, stone, and a roaring fireplace at 8,000 feet. Click out of your skis straight onto the deck, then thaw out in the private hot tub under the stars. Sleeps the whole crew.',
      amenities: ['Wifi', 'Kitchen', 'Hot tub', 'Fireplace', 'Ski-in/ski-out', 'Mountain view', 'Free parking', 'Heating', 'Washer', 'Dryer', 'Pets allowed'],
      photos: [img('1518780664697-55e3ad937233'), img('1493809842364-78817add7ffb'), img('1600585152220-90363fe7e115'), img('1502672260266-1c1ef2d93688'), img('1522708323590-d24dbb6b0267')],
      pricing: { nightly: 980, weekendNightly: 1200, weeklyDiscountPct: 10, monthlyDiscountPct: 25, cleaningFee: 275 },
      minNights: 2, instantBook: true,
    },
    {
      host: priya,
      title: 'Downtown Austin Loft, Steps from Rainey St.',
      type: 'Apartment',
      city: 'Austin', state: 'TX', lat: 30.2585, lng: -97.7386,
      bedrooms: 2, beds: 2, bathrooms: 2, maxGuests: 4,
      desc: 'A light-drenched loft in the heart of it all — exposed brick, 14-ft ceilings, and a rooftop pool with skyline views. Walk to live music, tacos, and the lake trail.',
      amenities: ['Wifi', 'Kitchen', 'Pool', 'Gym', 'Air conditioning', 'Workspace', 'Washer', 'Dryer', 'Free parking'],
      photos: [img('1560448204-e02f11c3d0e2'), img('1502005229762-cf1b2da7c5d6'), img('1600121848594-d8644e57abab'), img('1600047509807-ba8f99d2cdde')],
      pricing: { nightly: 265, weekendNightly: 340, weeklyDiscountPct: 15, monthlyDiscountPct: 35, cleaningFee: 90 },
      minNights: 2, instantBook: true,
    },
    {
      host: sofia,
      title: 'Art Deco Retreat on Miami Beach',
      type: 'Condo',
      city: 'Miami Beach', state: 'FL', lat: 25.7907, lng: -80.1300,
      bedrooms: 3, beds: 4, bathrooms: 2, maxGuests: 6,
      desc: 'Pastel-perfect Deco charm one block from the sand. Sip your morning cortadito on the balcony, then walk to Ocean Drive. Turquoise pool and cabanas downstairs.',
      amenities: ['Wifi', 'Kitchen', 'Pool', 'Beach access', 'Air conditioning', 'Free parking', 'Gym', 'Patio'],
      photos: [img('1522708323590-d24dbb6b0267'), img('1600607687939-ce8a6c25118c'), img('1600566753086-00f18fb6b3ea'), img('1600585154340-be6161a56a0c')],
      pricing: { nightly: 420, weekendNightly: 520, weeklyDiscountPct: 12, monthlyDiscountPct: 30, cleaningFee: 130 },
      minNights: 2, instantBook: false,
    },
    {
      host: marcus,
      title: 'Lakefront A-Frame at Lake Tahoe',
      type: 'Cabin',
      city: 'Lake Tahoe', state: 'CA', lat: 39.0968, lng: -120.0324,
      bedrooms: 3, beds: 4, bathrooms: 2, maxGuests: 7,
      desc: 'A classic A-frame right on the water with a private dock. Paddleboard at sunrise, grill on the deck at sunset, and fall asleep to the sound of the lake.',
      amenities: ['Wifi', 'Kitchen', 'Lake access', 'Fireplace', 'Mountain view', 'Free parking', 'Heating', 'BBQ grill', 'Pets allowed', 'Patio'],
      photos: [img('1449844908441-8829872d2607'), img('1493809842364-78817add7ffb'), img('1502672260266-1c1ef2d93688'), img('1600585152220-90363fe7e115')],
      pricing: { nightly: 510, weekendNightly: 640, weeklyDiscountPct: 14, monthlyDiscountPct: 32, cleaningFee: 160 },
      minNights: 2, instantBook: true,
    },
    {
      host: priya,
      title: 'Restored Craftsman in East Nashville',
      type: 'House',
      city: 'Nashville', state: 'TN', lat: 36.1780, lng: -86.7370,
      bedrooms: 3, beds: 3, bathrooms: 2, maxGuests: 6,
      desc: 'A lovingly restored 1920s Craftsman with a wraparound porch and a record player stocked with vinyl. Walk to the best coffee, honky-tonks, and hot chicken in town.',
      amenities: ['Wifi', 'Kitchen', 'Air conditioning', 'Workspace', 'Washer', 'Dryer', 'Free parking', 'Fireplace', 'Pets allowed', 'Patio'],
      photos: [img('1512917774080-9991f1c4c750'), img('1600596542815-ffad4c1539a9'), img('1600607687939-ce8a6c25118c'), img('1600566753086-00f18fb6b3ea')],
      pricing: { nightly: 240, weekendNightly: 310, weeklyDiscountPct: 15, monthlyDiscountPct: 38, cleaningFee: 85 },
      minNights: 2, instantBook: true,
    },
    {
      host: sofia,
      title: 'Desert Modern Escape in Scottsdale',
      type: 'House',
      city: 'Scottsdale', state: 'AZ', lat: 33.4942, lng: -111.9261,
      bedrooms: 4, beds: 5, bathrooms: 3, maxGuests: 8,
      desc: 'Clean lines, warm concrete, and a heated pool framed by saguaros. Golf minutes away, Old Town nightlife closer still. Built for sun-soaked long stays.',
      amenities: ['Wifi', 'Kitchen', 'Pool', 'Hot tub', 'Air conditioning', 'Free parking', 'EV charger', 'Workspace', 'BBQ grill', 'Patio'],
      photos: [img('1568605114967-8130f3a36994'), img('1600585154340-be6161a56a0c'), img('1600210492486-724fe5c67fb0'), img('1600607687939-ce8a6c25118c')],
      pricing: { nightly: 380, weekendNightly: 470, weeklyDiscountPct: 16, monthlyDiscountPct: 40, cleaningFee: 120 },
      minNights: 3, instantBook: true,
    },
    {
      host: marcus,
      title: 'Historic Savannah Carriage House',
      type: 'House',
      city: 'Savannah', state: 'GA', lat: 32.0746, lng: -81.0912,
      bedrooms: 2, beds: 2, bathrooms: 2, maxGuests: 4,
      desc: 'Tucked behind a wrought-iron gate on a cobblestone lane, this romantic carriage house opens onto a private courtyard garden dripping with Spanish moss.',
      amenities: ['Wifi', 'Kitchen', 'Air conditioning', 'Workspace', 'Washer', 'Free parking', 'Patio', 'Fireplace'],
      photos: [img('1570129477492-45c003edd2be'), img('1600596542815-ffad4c1539a9'), img('1522708323590-d24dbb6b0267'), img('1600566753086-00f18fb6b3ea')],
      pricing: { nightly: 210, weekendNightly: 270, weeklyDiscountPct: 13, monthlyDiscountPct: 33, cleaningFee: 75 },
      minNights: 2, instantBook: false,
    },
    {
      host: priya,
      title: 'Big Bear Treehouse Cabin with Hot Tub',
      type: 'Cabin',
      city: 'Big Bear Lake', state: 'CA', lat: 34.2439, lng: -116.9114,
      bedrooms: 2, beds: 3, bathrooms: 1, maxGuests: 5,
      desc: 'A cozy cabin among the pines with a wood stove, a game loft, and a bubbling hot tub on the deck. Ten minutes to the slopes, five to the lake.',
      amenities: ['Wifi', 'Kitchen', 'Hot tub', 'Fireplace', 'Mountain view', 'Free parking', 'Heating', 'Pets allowed', 'BBQ grill'],
      photos: [img('1493809842364-78817add7ffb'), img('1518780664697-55e3ad937233'), img('1502672260266-1c1ef2d93688'), img('1600585152220-90363fe7e115')],
      pricing: { nightly: 195, weekendNightly: 260, weeklyDiscountPct: 12, monthlyDiscountPct: 30, cleaningFee: 70 },
      minNights: 2, instantBook: true,
    },
    {
      host: sofia,
      title: 'Sunlit Brownstone Floor in Brooklyn',
      type: 'Apartment',
      city: 'Brooklyn', state: 'NY', lat: 40.6782, lng: -73.9442,
      bedrooms: 2, beds: 2, bathrooms: 1, maxGuests: 4,
      desc: 'A full parlor floor in a classic Park Slope brownstone — original moldings, a marble mantel, and a leafy backyard. Trains, cafés, and Prospect Park all around the corner.',
      amenities: ['Wifi', 'Kitchen', 'Air conditioning', 'Workspace', 'Washer', 'Dryer', 'Heating', 'Patio'],
      photos: [img('1600121848594-d8644e57abab'), img('1560448204-e02f11c3d0e2'), img('1502005229762-cf1b2da7c5d6'), img('1600047509807-ba8f99d2cdde')],
      pricing: { nightly: 285, weekendNightly: 340, weeklyDiscountPct: 14, monthlyDiscountPct: 36, cleaningFee: 95 },
      minNights: 3, instantBook: false,
    },
    {
      host: marcus,
      title: 'Red Rock Casita in Sedona',
      type: 'House',
      city: 'Sedona', state: 'AZ', lat: 34.8697, lng: -111.7610,
      bedrooms: 2, beds: 2, bathrooms: 2, maxGuests: 4,
      desc: 'Floor-to-ceiling windows frame the red rocks in every direction. Stargaze from the hot tub, hike from the door, and recharge in total desert quiet.',
      amenities: ['Wifi', 'Kitchen', 'Hot tub', 'Mountain view', 'Air conditioning', 'Free parking', 'Workspace', 'Patio', 'Heating'],
      photos: [img('1600585152220-90363fe7e115'), img('1568605114967-8130f3a36994'), img('1600210492486-724fe5c67fb0'), img('1600607687939-ce8a6c25118c')],
      pricing: { nightly: 320, weekendNightly: 400, weeklyDiscountPct: 15, monthlyDiscountPct: 34, cleaningFee: 100 },
      minNights: 2, instantBook: true,
    },
    {
      host: priya,
      title: 'Oceanfront Cottage in the Outer Banks',
      type: 'House',
      city: 'Outer Banks', state: 'NC', lat: 35.5585, lng: -75.4665,
      bedrooms: 4, beds: 6, bathrooms: 3, maxGuests: 9,
      desc: 'Toes in the sand from the back deck. A breezy, weathered-shingle beach house with an outdoor shower, crab traps, and endless dune views. Built for family summers.',
      amenities: ['Wifi', 'Kitchen', 'Beach access', 'Ocean view', 'Air conditioning', 'Free parking', 'Washer', 'Dryer', 'BBQ grill', 'Patio', 'Pets allowed'],
      photos: [img('1600596542815-ffad4c1539a9'), img('1512917774080-9991f1c4c750'), img('1449844908441-8829872d2607'), img('1600566753086-00f18fb6b3ea')],
      pricing: { nightly: 460, weekendNightly: 580, weeklyDiscountPct: 16, monthlyDiscountPct: 30, cleaningFee: 150 },
      minNights: 3, instantBook: false,
    },
  ];

  const reviewSnippets = [
    'Absolutely stunning — even better than the photos. The host thought of everything.',
    'One of the best stays we’ve ever had. Spotless, stylish, and the location can’t be beat.',
    'Check-in was seamless and the space was immaculate. We’re already planning our return.',
    'Incredible views and so comfortable. The kitchen made cooking in a joy.',
    'Perfect for our group. Great communication from the host and a dream location.',
    'Cozy, quiet, and beautifully designed. We didn’t want to leave.',
    'Everything worked flawlessly and it felt like home. Highly recommend.',
    'The photos don’t do it justice. Five stars all around.',
  ];

  for (const item of L) {
    const listing = {
      id: id(),
      hostId: item.host.id,
      title: item.title,
      description: item.desc,
      type: item.type,
      city: item.city,
      state: item.state,
      lat: item.lat,
      lng: item.lng,
      bedrooms: item.bedrooms,
      beds: item.beds,
      bathrooms: item.bathrooms,
      maxGuests: item.maxGuests,
      amenities: item.amenities,
      photos: item.photos,
      pricing: item.pricing,
      minNights: item.minNights,
      instantBook: item.instantBook,
      blockedDates: [],
      createdAt: isoAgo(Math.floor(Math.random() * 200) + 30),
    };
    db.listings.push(listing);

    // 3–5 reviews per listing.
    const n = 3 + Math.floor(Math.random() * 3);
    for (let i = 0; i < n; i++) {
      const reviewer = reviewers[(i + L.indexOf(item)) % reviewers.length];
      db.reviews.push({
        id: id(),
        listingId: listing.id,
        guestId: reviewer.id,
        rating: Math.random() < 0.8 ? 5 : 4,
        comment: reviewSnippets[(i + L.indexOf(item)) % reviewSnippets.length],
        createdAt: isoAgo(Math.floor(Math.random() * 120) + 5),
      });
    }
  }

  // A couple of demo bookings for the demo guest (one past, one upcoming).
  const first = db.listings[2];
  const second = db.listings[5];
  db.bookings.push({
    id: id(), listingId: first.id, guestId: demo.id,
    checkIn: daysFromNow(-40), checkOut: daysFromNow(-36), guests: 2,
    nights: 4, subtotal: 1100, cleaningFee: 90, serviceFee: 132, taxes: 95, total: 1417,
    status: 'completed', createdAt: isoAgo(50),
  });
  db.bookings.push({
    id: id(), listingId: second.id, guestId: demo.id,
    checkIn: daysFromNow(20), checkOut: daysFromNow(25), guests: 4,
    nights: 5, subtotal: 1200, cleaningFee: 85, serviceFee: 144, taxes: 103, total: 1532,
    status: 'confirmed', createdAt: isoAgo(3),
  });

  db.favorites.push({ userId: demo.id, listingId: db.listings[0].id });
  db.favorites.push({ userId: demo.id, listingId: db.listings[4].id });

  db.meta.seeded = true;
}

// Allow `node server/seed.js --force`
if (import.meta.url === `file://${process.argv[1]}`) {
  load();
  seedIfEmpty(process.argv.includes('--force'));
  flush();
  console.log('Seeded database with', getDb().listings.length, 'listings.');
}
