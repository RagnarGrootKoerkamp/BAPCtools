import java.io.*;
import java.util.*;

public class Paul {
    public static void main(String[] args) throws IOException {
        Scanner sc = new Scanner(System.in);
        sc.nextLine();
        int n = sc.nextInt();
        for (int i = 0; i < n; i++) {
            String s = sc.next();
            for (char c : s.toCharArray()) {
                System.out.print((char) (((c - 1) ^ 1) + 1));
            }
            System.out.println();
        }
    }
}
