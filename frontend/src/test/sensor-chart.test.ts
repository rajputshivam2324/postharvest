import { temperatureDomain, timeLabel } from '../components/SensorChart';

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

describe('timeLabel', () => {
  const noon = new Date(2026, 10, 19, 14, 5).getTime();
  it('shows only the clock time for a short range', () => {
    expect(timeLabel(noon, 6 * 3600000)).not.toMatch(/Nov/);
  });
  it('adds the date once the range is longer than a day and a half', () => {
    expect(timeLabel(noon, 6 * 86400000)).toMatch(/19/);
    expect(timeLabel(noon, 6 * 86400000)).toMatch(/Nov/);
  });
});
