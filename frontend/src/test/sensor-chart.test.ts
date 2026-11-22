import { temperatureDomain } from '../components/SensorChart';

describe('temperatureDomain', () => {
  it('keeps a wide fixed range so a cold night near 10 C is visible', () => {
    expect(temperatureDomain(25.6, 25.9)).toEqual([5, 40]);
    expect(temperatureDomain(10.2, 18)).toEqual([5, 40]);
  });
  it('widens in steps of 5 when readings leave the range', () => {
    expect(temperatureDomain(-3.2, 30)).toEqual([-5, 40]);
    expect(temperatureDomain(20, 43.1)).toEqual([5, 45]);
  });
});
